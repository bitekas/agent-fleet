#!/usr/bin/env python3
"""Google Sheets and Drive as the agent's own Workspace user.

One minter, one transport, one CLI. A second copy of the JWT dance is a bug:
the two identities a service-account key can present - the bare service account
and the Workspace user it is delegated to impersonate - differ by ONE claim
(`sub`), and a second implementation is where that claim silently goes missing.

    ./gsheets.py whoami
    ./gsheets.py get <spreadsheet-id>
    ./gsheets.py values <spreadsheet-id> 'Sheet1!A1:D20'
    ./gsheets.py write <spreadsheet-id> 'Sheet1!A1:B2' '[["a","b"],["c","d"]]'
    ./gsheets.py batch <spreadsheet-id> requests.json
    ./gsheets.py create 'A new spreadsheet'
    ./gsheets.py share <file-id> someone@example.com --role writer
    ./gsheets.py delete <file-id>
    ./gsheets.py list "name contains 'tracker'"

Importable, and that is the supported way to do anything this CLI does not:

    import gsheets
    gsheets.token(gsheets.scope('sheets'))     # an access token, cached
    gsheets.call(url, scope, method=, data=, params=)
    gsheets.drive_list("mimeType='application/vnd.google-apps.spreadsheet'")

================================================================================
WHY THE SUBJECT IS THE DEFAULT, AND WHAT BREAKS WITHOUT IT
================================================================================
The key is a service account holding DOMAIN-WIDE DELEGATION for an explicit list
of scopes. A JWT-bearer assertion carrying `sub: <user>` mints a token that IS
that Workspace user: it reads and writes everything shared to that user, and
what it creates is owned by that user and counts against THAT USER'S storage.

That last clause is not a detail. A service account has NO Drive storage quota
of its own, so a create without a subject fails `403 storageQuotaExceeded` -
which is the same trap as the 403 below, one API over.

⚠️ THE GRANT IS PER SCOPE, AND READ AND WRITE ARE DIFFERENT SCOPES. An install
whose grant lists a read-only Drive scope reads and lists as the user and is
refused - `403 insufficient authentication scopes` - on sharing, trashing and
deleting, INCLUDING on files that user owns outright. Widening it is an
administrator's edit; editing `scopes` in config.json alone mints nothing.

Without `sub` the token is the bare service account, which is a different
principal with a different address (`...gserviceaccount.com`) and which was
shared nothing. The symptom is a `403 PERMISSION_DENIED` on the very document a
person just shared, and the two identities look like ONE from the outside - so
the default here is the subject, and dropping it is the explicit `--sa-only`.

`--sa-only` exists for exactly two jobs: proving that a denial is about the
SHARE and not about the delegation, and touching something owned by the service
account itself. It is not a fallback to try when a call fails.

================================================================================
WHAT THE FAILURES MEAN - THEY ARE NOT INTERCHANGEABLE
================================================================================
* `unauthorized_client` AT THE MINT - the Workspace has no delegation grant for
  this service account and these scopes, or the grant omits the scope asked
  for. Nothing was reached; no API was called. Only a Workspace admin fixes it.
* `invalid_grant` AT THE MINT - the subject is not a real, live user in that
  Workspace (a typo, a group address, a suspended account), or the machine
  clock is far off. Also pre-API.
* `403` FROM AN API - FOUR unrelated causes wear this one status, which is why
  the status alone is never the diagnosis and every branch below matches on the
  MESSAGE:
    - the document is not shared with this identity (the common one);
    - `SERVICE_DISABLED` - the API is not enabled on the key's cloud project;
    - `insufficient authentication scopes` - the identity is right and the
      SCOPE is too narrow. It denies the acting user's own files too, so
      reading it as a sharing problem sends the reader to ask for access they
      already hold;
    - `storageQuotaExceeded` - a create with no subject, against a service
      account that has no storage.
* `404` FROM DRIVE - Drive HIDES EXISTENCE. "Not shared to you" and "no such
  file" are the same 404 on purpose, so a 404 is never evidence that a file is
  gone.
* `404` FROM SHEETS - the spreadsheet id does not resolve for this identity.

That ordering is the whole diagnostic: a token that MINTS proves the delegation
exists, which is what separates "not delegated" from "not shared".

================================================================================
THE KEY AND THE TOKEN NEVER REACH STDOUT
================================================================================
`whoami` mints a token and prints the identity it acts as, never the token.
Every error body that could conceivably carry one goes through `scrub()` before
it is printed. That is not decoration: an access token in a transcript, a log or
a pasted terminal line is a live credential for as long as it lasts, and the one
place a token legitimately appears - the mint response - is the same code path
that renders a mint FAILURE. If scrub() is ever deleted, a malformed-but-200
token response rendered as an error puts a bearer token into the output. Its
test is gsheets.test.py section 6; if that section is removed, this paragraph is
the argument for putting it back.

================================================================================
EXIT CODES
================================================================================
    0  ok
    1  usage or configuration error (nothing was attempted)
    2  the credential file is missing, unreadable, or not a service-account key
    3  the mint was refused - delegation or subject (no API was reached)
    4  an API call failed or was denied

2, 3 and 4 are deliberately three codes and not one. They have three different
repairs, performed by three different people, and a caller that collapses them
reports "permission denied" for a machine with no key on it.
"""
import argparse
import errno
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# realpath, never abspath: imported or run through an agent's skill link, the
# unresolved path is the link directory, and three levels up from there is not the
# fleet tree whose lib/ holds fleetlib.
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def _fleetlib_paths():
    """fleetlib's paths module, imported from this fleet tree. Only the two lookups
    that need the install or the host import it, so a caller that passes a config
    and a key path of its own needs no fleet install at all."""
    sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
    from fleetlib import paths
    return paths


def default_config_path():
    """The install's config.json for this skill (fleetlib's install context)."""
    try:
        return str(_fleetlib_paths().skill_context("google-spreadsheet") / "config.json")
    except Exception as e:  # noqa: BLE001 - any resolution failure is a config fault
        raise ConfigError(f"cannot resolve the install's config.json ({type(e).__name__}: "
                          f"{e}); pass --config or set GSHEETS_CONFIG") from None

# Every value this module needs that differs per install is a config key. The
# names are listed here so a missing one is reported by NAME rather than as a
# KeyError from somewhere inside a call.
REQUIRED_KEYS = (
    "identity.agent",
    "identity.subject_template",
    "credential.key_path",
    "api.sheets_base",
    "api.drive_base",
    "scopes.sheets",
    "scopes.drive",
)

# The seam every network call goes through, so the test suite can run the whole
# module - mint, cache, classification, CLI - with no network and no key. Tests
# replace this attribute; nothing else may call urlopen directly.
_urlopen = urllib.request.urlopen

# (scope, subject) -> (access_token, absolute expiry). Keyed by BOTH because one
# process routinely holds tokens for two scopes and for more than one subject,
# and a cache keyed on scope alone hands a token for the wrong identity to a
# caller that asked for another - which succeeds, writes to the wrong Drive, and
# reports nothing. gsheets.test.py section 4 is the control for that.
_TOKENS = {}

_SENTINEL = object()


class ConfigError(Exception):
    """Bad or missing configuration. Nothing was attempted."""


class CredentialError(Exception):
    """The service-account key is missing, unreadable or not a key."""


class MintError(Exception):
    """The token endpoint refused the assertion. No API was reached."""


class ApiError(Exception):
    """An API call failed. Carries the HTTP status."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# Secrets never reach the output
# --------------------------------------------------------------------------

# Google OAuth access tokens are `ya29.` (and historically `ya30.`) followed by
# a long opaque run; refresh tokens are `1//`. The JSON forms are matched too
# because a body is usually rendered as-is.
_SECRET_PATTERNS = (
    re.compile(r'("(?:access_token|id_token|refresh_token|private_key)"\s*:\s*")[^"]*(")'),
    re.compile(r"\bya2\d\.[A-Za-z0-9._\-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


def scrub(text):
    """Replace anything token- or key-shaped in TEXT with `[redacted]`.

    Applied to every error body this module prints. See the header: the mint
    response is the one HTTP body in this module that legitimately contains a
    bearer token, and it is rendered by the same code that renders a mint
    failure. Removing this function does not break any call - it silently moves
    credentials into stdout, which is the failure mode with no symptom.
    """
    if not isinstance(text, str):
        text = str(text)
    out = _SECRET_PATTERNS[0].sub(r"\1[redacted]\2", text)
    out = _SECRET_PATTERNS[1].sub("[redacted]", out)
    out = _SECRET_PATTERNS[2].sub("[redacted]", out)
    return out


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

_DEFAULTED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}]*)\}")
_MAX_EXPANSIONS = 10


def expand_path(raw):
    """Expand `${VAR:-default}`, then `$VAR`, then a leading `~`.

    All three, in this order, because no single stdlib call does them:
    expandvars knows nothing about `:-` or `~`, expanduser knows nothing about
    variables. `or` rather than a dict default gives shell `:-` semantics, where
    an EMPTY variable also takes the default.

    An unset variable with no default is left as the literal `$NAME`. The open
    then fails naming the unexpanded text, which names the variable nobody set.
    That is intended: substituting a guess would read a DIFFERENT agent's key
    and act as a different principal, which succeeds.

    The loop is bounded rather than `while it changes`: a variable whose value
    re-introduces the pattern would otherwise never terminate, and a helper that
    hangs is indistinguishable from a slow network.
    """
    for _ in range(_MAX_EXPANSIONS):
        prev = raw
        raw = _DEFAULTED.sub(lambda m: os.environ.get(m.group(1)) or m.group(2), raw)
        if raw == prev:
            break
    return os.path.expanduser(os.path.expandvars(raw))


def _dig(doc, dotted):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _SENTINEL
        cur = cur[part]
    return cur


def load_config(path=None):
    """Read and validate the config. Raises ConfigError naming the key.

    A missing key is fatal and never defaulted. Every value in REQUIRED_KEYS
    selects an IDENTITY or an ENDPOINT, and a guessed one fails silently in the
    worst available way: a guessed subject acts as the wrong person, a guessed
    key path reads another agent's credential, a guessed API base sends a signed
    bearer token to a host nobody chose.
    """
    path = path or os.environ.get("GSHEETS_CONFIG") or default_config_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError(
            f"no config at {path} (copy config.example.json to config.json in the "
            f"install context and fill it in, or set GSHEETS_CONFIG)")
    except OSError as e:
        raise ConfigError(f"config at {path} cannot be read "
                          f"({errno.errorcode.get(e.errno, e.errno)}: {e.strerror or e})")
    except ValueError as e:
        raise ConfigError(f"config at {path} does not parse: {e}")
    if not isinstance(cfg, dict):
        raise ConfigError(f"config at {path} is not a JSON object")
    for key in REQUIRED_KEYS:
        value = _dig(cfg, key)
        if value is _SENTINEL or value in (None, ""):
            raise ConfigError(f"config at {path} is missing required key '{key}'")
    cfg["_path"] = path
    return cfg


_CONFIG = None


def config(path=None):
    """The loaded config, cached per process."""
    global _CONFIG
    if _CONFIG is None or path:
        _CONFIG = load_config(path)
    return _CONFIG


def agent(cfg=None):
    cfg = cfg or config()
    return os.environ.get("GSHEETS_AGENT") or _dig(cfg, "identity.agent")


def default_subject(cfg=None):
    """The Workspace user this install acts as unless told otherwise.

    `GSHEETS_SUBJECT` overrides it for a whole process; `--as` overrides it for
    one invocation. Neither changes the KEY that is used - one agent's key can
    only impersonate users its delegation grant covers.
    """
    cfg = cfg or config()
    env = os.environ.get("GSHEETS_SUBJECT")
    if env:
        return env
    return _dig(cfg, "identity.subject_template").format(agent=agent(cfg))


def scope(name, cfg=None):
    """The OAuth scope URL configured under `scopes.<name>`."""
    cfg = cfg or config()
    value = _dig(cfg, "scopes." + name)
    if value is _SENTINEL:
        raise ConfigError(f"config at {cfg.get('_path')} has no scope '{name}' "
                          f"(add it under 'scopes')")
    return value


def agent_home(name):
    """`<agents_root>/<name>`: the agent's home, from the fleet's host settings."""
    try:
        root = _fleetlib_paths().host()["agents_root"]
    except Exception as e:  # noqa: BLE001 - any failure to read it is a config fault
        raise ConfigError(f"credential.key_path uses {{home}}, and the agents root cannot be "
                          f"read from the fleet's host settings ({type(e).__name__}: {e})") from None
    return os.path.join(os.path.expanduser(str(root)), name)


def key_path(cfg=None):
    """The absolute path of this agent's service-account key.

    `{agent}`, `{default_subject}` and `{home}` are substituted BEFORE variable
    and `~` expansion. `{home}` is that agent's home, `<agents_root>/<agent>`,
    with the agents root read from the fleet's host settings - only when the
    template uses it, so a key path without it needs no fleet install.
    `{default_subject}` is the install's own user and deliberately NOT whatever
    `--as` asked for: impersonating another user does not change which key file
    signs the assertion, and formatting the path with the override would send
    the loader looking for a key that belongs to somebody else.
    """
    cfg = cfg or config()
    template = _dig(cfg, "credential.key_path")
    own = _dig(cfg, "identity.subject_template").format(agent=agent(cfg))
    fields = {"agent": agent(cfg), "default_subject": own}
    if "{home}" in template:
        fields["home"] = agent_home(agent(cfg))
    return expand_path(template.format(**fields))


def load_key(cfg=None):
    """Open and parse the service-account key. Raises CredentialError.

    OPENED, not stat'ed. A key that is present, the right size and unreadable
    passes every exists()/getsize() test and fails at the first signature, so
    the only test worth making here is the one the caller is about to make.
    """
    path = key_path(cfg)
    try:
        with open(path, encoding="utf-8") as f:
            key = json.load(f)
    except FileNotFoundError:
        raise CredentialError(
            f"no service-account key at {path}. Ask a Workspace/GCP admin to issue "
            f"one for this agent and install it with `install -m 0600 <downloaded>.json "
            f"{path}`.")
    except OSError as e:
        raise CredentialError(
            f"the service-account key at {path} cannot be read "
            f"({errno.errorcode.get(e.errno, e.errno)}: {e.strerror or e}). A machine "
            f"admin repairs it: `sudo chown $(id -un) {path} && chmod 0600 {path}`.")
    except ValueError as e:
        raise CredentialError(f"the service-account key at {path} does not parse as JSON: {e}")
    missing = [f for f in ("client_email", "private_key", "token_uri") if not key.get(f)]
    if missing:
        raise CredentialError(
            f"{path} is not a service-account key: it has no {', '.join(missing)}. "
            f"An OAuth client secret and a service-account key are both JSON and look "
            f"alike; only the second one can be delegated.")
    return key


# --------------------------------------------------------------------------
# The mint
# --------------------------------------------------------------------------

def _mint_error(subject, body, status):
    """Turn a token-endpoint refusal into the one sentence that names its repair."""
    text = scrub(body)
    try:
        code = json.loads(body).get("error", "")
    except ValueError:
        code = ""
    if code == "unauthorized_client":
        return (f"unauthorized_client: the Workspace has no domain-wide delegation grant "
                f"for this service account and this scope, so no token exists to try any "
                f"API with. A Workspace admin adds the service account's numeric client "
                f"id and the scope under Security > API controls > Domain-wide "
                f"delegation. (subject {subject})")
    if code == "invalid_grant":
        return (f"invalid_grant: '{subject}' is not a live user in the Workspace this key "
                f"is delegated on (a typo, a group address, or a suspended account), or "
                f"this machine's clock is far out of step. Nothing was reached.")
    return f"HTTP {status} from the token endpoint: {text[:400]}"


def token(scope_url, subject=_SENTINEL, cfg=None):
    """An access token for SCOPE_URL, acting as SUBJECT. Cached per (scope, subject).

    SUBJECT defaults to the install's configured Workspace user. Pass None
    explicitly for the bare service account - see the header for why that is not
    a fallback.
    """
    cfg = cfg or config()
    if subject is _SENTINEL:
        subject = default_subject(cfg)
    cache_key = (scope_url, subject)
    hit = _TOKENS.get(cache_key)
    if hit and hit[1] > time.time() + 60:
        return hit[0]

    import jwt  # imported here so every offline path works without PyJWT installed

    key = load_key(cfg)
    now = int(time.time())
    claims = {
        "iss": key["client_email"],
        "scope": scope_url,
        "aud": key["token_uri"],
        "iat": now,
        "exp": now + 3600,
    }
    # The ONE claim that separates the two identities. Set only when a subject
    # was asked for, and never defaulted to the client_email: a `sub` naming the
    # service account itself is not the same request as no `sub` at all.
    if subject:
        claims["sub"] = subject
    assertion = jwt.encode(claims, key["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    request = urllib.request.Request(key["token_uri"], data=body)
    try:
        with _urlopen(request) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise MintError(_mint_error(subject, e.read().decode("utf-8", "replace"), e.code))
    except urllib.error.URLError as e:
        raise MintError(f"the token endpoint could not be reached: {e.reason}")
    access = payload.get("access_token")
    if not access:
        # Deliberately does NOT echo the body. A 200 with no access_token is the
        # one case where the body plausibly holds a credential in a shape this
        # code did not expect, and printing it is the leak scrub() exists for.
        raise MintError("the token endpoint answered 200 with no access_token")
    _TOKENS[cache_key] = (access, now + int(payload.get("expires_in", 3600)))
    return access


def forget_tokens():
    """Drop every cached token. For tests and for a long-lived process that has
    had its subject changed underneath it."""
    _TOKENS.clear()


# --------------------------------------------------------------------------
# The transport
# --------------------------------------------------------------------------

def _api_error(status, url, body, subject):
    text = scrub(body)
    lowered = text.lower()
    if status == 403 and ("service_disabled" in lowered
                          or "has not been used in project" in lowered
                          or "is disabled" in lowered):
        return (f"HTTP 403 SERVICE NOT ENABLED - this is NOT a sharing problem. The API "
                f"is not enabled on the project that issued this key; enable it there "
                f"and retry. {text[:300]}")
    # The THIRD meaning of 403, and the one that looks most like the first. The
    # token is the right identity and the document may well be the identity's
    # OWN file; the SCOPE it was minted for does not cover this call. Reported as
    # a share problem it sends the reader to ask for access they already have -
    # measured against a spreadsheet the acting user owns outright, refused under
    # a read-only Drive scope.
    if status == 403 and ("insufficient authentication scopes" in lowered
                          or "insufficient permission" in lowered
                          or "access_token_scope_insufficient" in lowered):
        return (f"HTTP 403 INSUFFICIENT SCOPE - this is NOT a sharing problem either. The "
                f"token is {subject or 'the bare service account'} and it is the right "
                f"identity; the scope it was minted for does not cover this call. Widen "
                f"the delegation grant AND the matching entry in `scopes` - a narrower "
                f"scope here denies even the acting user's OWN files. {text[:200]}")
    if status == 403 and "storagequotaexceeded" in lowered:
        return (f"HTTP 403 STORAGE QUOTA EXCEEDED for "
                f"{subject or 'the bare service account'}. A service account has NO Drive "
                f"storage of its own, so this is what creating a file looks like when the "
                f"subject was dropped: set it and the file is created in that user's "
                f"Drive against that user's quota. {text[:200]}")
    if status == 403:
        return (f"HTTP 403 PERMISSION_DENIED for {subject or 'the bare service account'} "
                f"on {url}. The identity is real (the token minted); the document is not "
                f"shared to it. Ask for it to be shared with {subject or 'this account'}. "
                f"{text[:200]}")
    if status == 404 and "/drive/" in url:
        return (f"HTTP 404 from Drive for {subject or 'the bare service account'}. Drive "
                f"hides existence: 'not shared to you' and 'no such file' are the same "
                f"404, so this is not evidence the file is gone. {text[:200]}")
    if status == 404:
        return (f"HTTP 404 - no such spreadsheet for "
                f"{subject or 'the bare service account'}: {url}. {text[:200]}")
    if status == 401:
        return f"HTTP 401 - the token was rejected: {text[:300]}"
    return f"HTTP {status} {url}: {text[:400]}"


def call(url, scope_url, method="GET", data=None, raw=False, params=None, subject=_SENTINEL,
         cfg=None):
    """One HTTP call against a Google API with a token for SCOPE_URL."""
    cfg = cfg or config()
    if subject is _SENTINEL:
        subject = default_subject(cfg)
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, method=method,
        headers={"Authorization": "Bearer " + token(scope_url, subject, cfg),
                 "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with _urlopen(request) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        raise ApiError(_api_error(e.code, url, e.read().decode("utf-8", "replace"), subject),
                       status=e.code)
    except urllib.error.URLError as e:
        raise ApiError(f"{url} could not be reached: {e.reason}")
    if raw:
        return payload
    return json.loads(payload) if payload else {}


def drive_list(q=None, subject=_SENTINEL, cfg=None, fields=None):
    """Every Drive file matching Q, following pagination.

    ⚠️ `supportsAllDrives` and `includeItemsFromAllDrives` are not optional and
    not defensive. Without BOTH, content on a shared drive is absent from the
    result with no error and no marker - a silently short list, which reads as
    "nothing is shared with me" and is the one failure mode here that looks
    exactly like a correct answer.
    """
    cfg = cfg or config()
    base = _dig(cfg, "api.drive_base").rstrip("/") + "/files"
    fields = fields or "nextPageToken,files(id,name,mimeType,modifiedTime,owners/emailAddress)"
    files, page = [], None
    while True:
        params = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                  "pageSize": 1000, "fields": fields}
        if q:
            params["q"] = q
        if page:
            params["pageToken"] = page
        result = call(base, scope("drive", cfg), params=params, subject=subject, cfg=cfg)
        files += result.get("files", [])
        page = result.get("nextPageToken")
        if not page:
            return files


# --------------------------------------------------------------------------
# Sheets and Drive operations, thin over call()
# --------------------------------------------------------------------------

def _sheet_url(cfg, spreadsheet_id, suffix=""):
    return _dig(cfg, "api.sheets_base").rstrip("/") + "/" + urllib.parse.quote(
        spreadsheet_id, safe="") + suffix


def _drive_url(cfg, suffix):
    return _dig(cfg, "api.drive_base").rstrip("/") + suffix


def spreadsheet(spreadsheet_id, subject=_SENTINEL, cfg=None):
    cfg = cfg or config()
    return call(_sheet_url(cfg, spreadsheet_id), scope("sheets", cfg),
                params={"fields": "spreadsheetId,properties.title,spreadsheetUrl,"
                                  "sheets.properties"},
                subject=subject, cfg=cfg)


def values(spreadsheet_id, a1_range, subject=_SENTINEL, cfg=None):
    cfg = cfg or config()
    url = _sheet_url(cfg, spreadsheet_id, "/values/" + urllib.parse.quote(a1_range, safe=""))
    return call(url, scope("sheets", cfg), subject=subject, cfg=cfg)


def write_values(spreadsheet_id, a1_range, rows, subject=_SENTINEL, cfg=None,
                 value_input_option="USER_ENTERED"):
    cfg = cfg or config()
    url = _sheet_url(cfg, spreadsheet_id, "/values/" + urllib.parse.quote(a1_range, safe=""))
    return call(url, scope("sheets", cfg), method="PUT",
                data={"values": rows},
                params={"valueInputOption": value_input_option},
                subject=subject, cfg=cfg)


def batch_update(spreadsheet_id, body, subject=_SENTINEL, cfg=None):
    """POST a `spreadsheets.batchUpdate` body - the only route to structure.

    Data validation (drop-downs), conditional formatting, frozen rows, column
    widths, merges, protected ranges and adding a sheet are all requests in
    this one call; the values endpoints can only carry cell CONTENT.
    """
    cfg = cfg or config()
    if isinstance(body, list):
        body = {"requests": body}
    return call(_sheet_url(cfg, spreadsheet_id, ":batchUpdate"), scope("sheets", cfg),
                method="POST", data=body, subject=subject, cfg=cfg)


def create(title, subject=_SENTINEL, cfg=None):
    """Create a spreadsheet. It is owned by the SUBJECT, not by the service
    account - which is the practical reason to keep the subject set: a file the
    bare service account owns is in nobody's Drive and no person can find it."""
    cfg = cfg or config()
    return call(_dig(cfg, "api.sheets_base"), scope("sheets", cfg), method="POST",
                data={"properties": {"title": title}}, subject=subject, cfg=cfg)


def share(file_id, email, role="reader", subject=_SENTINEL, cfg=None, notify=False):
    cfg = cfg or config()
    url = _drive_url(cfg, "/files/" + urllib.parse.quote(file_id, safe="") + "/permissions")
    return call(url, scope("drive", cfg), method="POST",
                data={"type": "user", "role": role, "emailAddress": email},
                params={"supportsAllDrives": "true",
                        "sendNotificationEmail": "true" if notify else "false"},
                subject=subject, cfg=cfg)


def trash(file_id, subject=_SENTINEL, cfg=None):
    """Move a file to the subject's Drive trash - RECOVERABLE, and the default.

    `delete` on the CLI does this. The permanent form is a separate flag because
    a file id is one paste away from being the wrong file id, and Drive's own
    delete has no undo; trash gives the 30 days in which a mistake is a nuisance
    rather than a loss.
    """
    cfg = cfg or config()
    url = _drive_url(cfg, "/files/" + urllib.parse.quote(file_id, safe=""))
    return call(url, scope("drive", cfg), method="PATCH", data={"trashed": True},
                params={"supportsAllDrives": "true"}, subject=subject, cfg=cfg)


def delete_permanently(file_id, subject=_SENTINEL, cfg=None):
    cfg = cfg or config()
    url = _drive_url(cfg, "/files/" + urllib.parse.quote(file_id, safe=""))
    return call(url, scope("drive", cfg), method="DELETE", raw=True,
                params={"supportsAllDrives": "true"}, subject=subject, cfg=cfg)


def about(subject=_SENTINEL, cfg=None):
    """Who the token actually is, according to Drive."""
    cfg = cfg or config()
    return call(_drive_url(cfg, "/about"), scope("drive", cfg),
                params={"fields": "user"}, subject=subject, cfg=cfg)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    """The whole CLI surface, built separately so the test can parse argv with
    no config, no key and no network."""
    p = argparse.ArgumentParser(
        prog="gsheets.py",
        description="Google Sheets and Drive as the agent's own Workspace user.")
    p.add_argument("--as", dest="subject", metavar="USER",
                   help="act as this Workspace user instead of the configured default")
    p.add_argument("--sa-only", action="store_true",
                   help="drop the subject and act as the bare service account "
                        "(diagnostic: proves whether a denial is about the share)")
    p.add_argument("--config", metavar="PATH", help="a config.json other than the default")
    p.add_argument("--json", action="store_true", help="print the raw API response")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="mint a token and print the identity it acts as")

    g = sub.add_parser("get", help="a spreadsheet's title and its sheets")
    g.add_argument("id")

    v = sub.add_parser("values", help="read an A1 range")
    v.add_argument("id")
    v.add_argument("range")

    w = sub.add_parser("write", help="write an A1 range from a JSON array of arrays")
    w.add_argument("id")
    w.add_argument("range")
    w.add_argument("rows", help="JSON, or @FILE, or - for stdin")
    w.add_argument("--raw", action="store_true",
                   help="RAW input: store values literally rather than parsing them as a "
                        "user's typing (dates, formulas, leading zeroes)")

    b = sub.add_parser("batch", help="POST a batchUpdate request body")
    b.add_argument("id")
    b.add_argument("file", help="a JSON file holding {\"requests\": [...]}, or - for stdin")

    c = sub.add_parser("create", help="create a spreadsheet owned by the acting user")
    c.add_argument("title")

    s = sub.add_parser("share", help="share a file with a person")
    s.add_argument("id")
    s.add_argument("email")
    s.add_argument("--role", default="reader",
                   choices=["reader", "commenter", "writer", "fileOrganizer", "organizer"])
    s.add_argument("--notify", action="store_true", help="send Google's share email")

    d = sub.add_parser("delete", help="move a file to the acting user's trash")
    d.add_argument("id")
    d.add_argument("--permanent", action="store_true",
                   help="delete irrecoverably instead of trashing")

    ls = sub.add_parser("list", help="what is shared with the acting user")
    ls.add_argument("query", nargs="?", help="a Drive `q` query")
    return p


def _rows_argument(text):
    if text == "-":
        text = sys.stdin.read()
    elif text.startswith("@"):
        with open(text[1:], encoding="utf-8") as f:
            text = f.read()
    rows = json.loads(text)
    if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
        raise ConfigError("the rows argument must be a JSON array of arrays, "
                          "e.g. '[[\"a\",\"b\"],[\"c\",\"d\"]]'")
    return rows


def _print_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def run(args):
    cfg = config(args.config)
    if args.sa_only and args.subject:
        raise ConfigError("--sa-only and --as are contradictory: one drops the subject, "
                          "the other sets it")
    subject = None if args.sa_only else (args.subject or default_subject(cfg))

    if args.command == "whoami":
        key = load_key(cfg)
        who = about(subject=subject, cfg=cfg).get("user", {})
        seen = (who.get("emailAddress") or "").strip()
        print(f"key          {key_path(cfg)}")
        print(f"client       {key['client_email']}")
        print(f"requested    {subject or '(none - bare service account)'}")
        print(f"drive says   {who.get('displayName', '?')} <{seen or '?'}>")
        # The point of the command. A token that mints is not yet proof that it
        # acts as the user you asked for: a config whose subject_template is
        # wrong mints perfectly and acts as somebody else. Only Drive's own
        # answer closes that, and only if it is COMPARED.
        if subject and seen.lower() != subject.lower():
            print(f"MISMATCH     a token was minted, but it acts as {seen}, not {subject}")
            return 4
        print("ok           the token acts as the identity that was asked for")
        return 0

    if args.command == "get":
        doc = spreadsheet(args.id, subject=subject, cfg=cfg)
        if args.json:
            _print_json(doc)
            return 0
        print(doc.get("properties", {}).get("title", "(untitled)"))
        print(doc.get("spreadsheetUrl", ""))
        for sheet in doc.get("sheets", []):
            props = sheet.get("properties", {})
            grid = props.get("gridProperties", {})
            print(f"  [{props.get('index')}] {props.get('title')}  "
                  f"sheetId={props.get('sheetId')}  "
                  f"{grid.get('rowCount', '?')}x{grid.get('columnCount', '?')}"
                  f"{'  frozen=' + str(grid['frozenRowCount']) if grid.get('frozenRowCount') else ''}")
        return 0

    if args.command == "values":
        got = values(args.id, args.range, subject=subject, cfg=cfg)
        if args.json:
            _print_json(got)
            return 0
        for row in got.get("values", []):
            print("\t".join("" if cell is None else str(cell) for cell in row))
        return 0

    if args.command == "write":
        rows = _rows_argument(args.rows)
        got = write_values(args.id, args.range, rows, subject=subject, cfg=cfg,
                           value_input_option="RAW" if args.raw else "USER_ENTERED")
        if args.json:
            _print_json(got)
            return 0
        print(f"updated {got.get('updatedRange')}: {got.get('updatedCells')} cells")
        return 0

    if args.command == "batch":
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        got = batch_update(args.id, json.loads(text), subject=subject, cfg=cfg)
        if args.json:
            _print_json(got)
            return 0
        print(f"{len(got.get('replies', []))} replies")
        return 0

    if args.command == "create":
        got = create(args.title, subject=subject, cfg=cfg)
        if args.json:
            _print_json(got)
            return 0
        print(got.get("spreadsheetId", ""))
        print(got.get("spreadsheetUrl", ""))
        return 0

    if args.command == "share":
        got = share(args.id, args.email, role=args.role, subject=subject, cfg=cfg,
                    notify=args.notify)
        if args.json:
            _print_json(got)
            return 0
        print(f"shared {args.id} with {args.email} as {args.role} (permission "
              f"{got.get('id')})")
        return 0

    if args.command == "delete":
        if args.permanent:
            delete_permanently(args.id, subject=subject, cfg=cfg)
            print(f"deleted {args.id} permanently")
        else:
            trash(args.id, subject=subject, cfg=cfg)
            print(f"trashed {args.id} (recoverable from the acting user's Drive trash)")
        return 0

    if args.command == "list":
        found = drive_list(args.query, subject=subject, cfg=cfg)
        if args.json:
            _print_json(found)
            return 0
        for f in found:
            owner = (f.get("owners") or [{}])[0].get("emailAddress", "")
            print(f"{f['id']}\t{f.get('modifiedTime', '')}\t{f.get('mimeType', '')}\t"
                  f"{owner}\t{f.get('name', '')}")
        print(f"{len(found)} file(s) visible to {subject or 'the bare service account'}",
              file=sys.stderr)
        return 0

    raise ConfigError(f"unknown command {args.command}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    # One line each, no traceback. A traceback for an API denial buries the one
    # sentence that names the repair under twenty frames of urllib, and every
    # exception below is an EXPECTED state of the world rather than a defect.
    except ConfigError as e:
        print(f"gsheets: {e}", file=sys.stderr)
        return 1
    except CredentialError as e:
        print(f"gsheets: {e}", file=sys.stderr)
        return 2
    except MintError as e:
        print(f"gsheets: {e}", file=sys.stderr)
        return 3
    except ApiError as e:
        print(f"gsheets: {e}", file=sys.stderr)
        return 4
    except ImportError as e:
        print(f"gsheets: {e}. PyJWT with its cryptography extra signs the assertion; "
              f"see installation/INSTRUCTION.md.", file=sys.stderr)
        return 2


def key_mode(cfg=None):
    """The key file's permission bits, for installation/check. Returns None when
    the file is not there - the caller distinguishes that from a wrong mode."""
    try:
        return stat.S_IMODE(os.stat(key_path(cfg)).st_mode)
    except OSError:
        return None


if __name__ == "__main__":
    sys.exit(main())
