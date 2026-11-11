#!/usr/bin/env python3
"""Read the newest Google verification code out of the recovery mailbox.

    read_recovery_code.py [--minutes N] [--config PATH]

Prints the code and NOTHING ELSE on stdout, so `$(...)` is the code. Everything
that is not the code - the reason no code was found, a config or credential
error - goes to stderr, and the exit code says which:

    0  a code was printed
    1  no code: nothing from Google in the mailbox within the window, or the
       newest such message carries no code the extractor recognises
    2  usage, config, or the minting helper could not be loaded
    3  the token mint was refused (delegation or subject - no API reached)
    4  the Gmail API call failed or was denied

WHAT IT IS FOR. During an agent's Claude Code sign-in (SKILL.md step 6, or the
human route in step 7e), Google can interpose a "Verify it's you" challenge that
sends a verification code to the account's RECOVERY EMAIL. Every agent account
on the fleet has the same recovery address (`recovery.mailbox` in config.json),
and the fleet's Workspace service account is delegated `gmail.readonly` over
that Workspace, so the reviving agent reads the code from that mailbox itself,
as that user, and types it into the challenge. No human is needed.

HOW IT MINTS. It does not carry a JWT implementation. The delegated token is
minted by the google-spreadsheet skill's helper, `gsheets.py`, the sibling skill
beside this one in the fleet tree (reached through the fleet root, below),
imported through its documented entry point:
`gsheets.call(url, scope_url, subject=<mailbox>)`. One minter on the machine,
one place where the `sub` claim is set: the second copy of that dance is where
the claim silently goes missing (gsheets.py's header owns the argument). The
key that signs is whichever key gsheets.py's own config names; this file never
opens a credential.

WHAT IT MATCHES. Messages from Google's account senders (`SENDERS`), listed
newest first, no older than `--minutes`, in a mailbox that may also hold other
mail. The code is a 6-digit group read with its surrounding words - "your
verification code is 123456", "G-123456" - and only when the message carries no
such phrase does a LONE 6-digit group count; a message holding several bare
6-digit groups and no phrase yields nothing rather than a guess, because a
wrong code typed into the challenge is a failed attempt against the account.

⚠️ THE FIXTURE IS SYNTHETIC. read_recovery_code.test.py pins the extractor
against `fixtures/recovery-code-mail.txt`, written in the shape Google's
verification mail is documented to take, not captured from one. The first live
challenge this reads is the first measurement of that shape: if it exits 1 on a
message you can see in the mailbox, the fixture is what to update, and the
extractor after it.
"""
import argparse
import base64
import html
import importlib.util
import json
import os
import re
import sys
import time

# realpath, never abspath: invoked through an agent's skill link, the unresolved
# path is the link directory, whose parent holds only the links an install chose -
# not the fleet tree the sibling minter lives in.
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GSHEETS = os.path.join(FLEET_ROOT, ".claude", "skills", "google-spreadsheet", "gsheets.py")

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Google's account-security senders. A challenge code never comes from anywhere
# else, and restricting the sender is what keeps a mailbox that also receives
# ordinary mail from handing back a 6-digit order number.
SENDERS = ("noreply@google.com", "no-reply@accounts.google.com")

# Newest first, so the first message that yields a code is the one to type.
# Gmail's `newer_than:` takes whole days; the minute window is applied here.
LIST_QUERY = "from:(" + " OR ".join(SENDERS) + ") newer_than:1d"
LIST_MAX = 10

# The phrase-anchored patterns first; the lone-number rule is applied by
# extract_code itself, not by a pattern, because it needs to COUNT candidates.
_PHRASED = (
    re.compile(r"\bG-(\d{6})\b"),
    re.compile(r"(?i)\bcode\b\W{0,3}(?:is|:)?\W{0,40}?(\d{6})\b"),
)
_BARE = re.compile(r"(?<![\d-])(\d{6})(?![\d-])")


class ConfigError(Exception):
    pass


class NoCode(Exception):
    pass


# --------------------------------------------------------------------------
# Config and the minting helper
# --------------------------------------------------------------------------

def default_config():
    """The install's config.json for this skill, resolved through fleetlib. Used only
    when neither --config nor $AGENT_REVIVE_CONFIG names one."""
    sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
    try:
        from fleetlib import paths
        return str(paths.skill_context("agent-revive") / "config.json")
    except Exception as e:  # noqa: BLE001 - any resolution failure is a config fault
        raise ConfigError(f"cannot resolve the install's config.json ({type(e).__name__}: "
                          f"{e}); pass --config or set AGENT_REVIVE_CONFIG")


def load_config(path=None):
    """The `recovery` block of the skill's config, keys checked by name, plus the
    path of the minting helper."""
    path = path or os.environ.get("AGENT_REVIVE_CONFIG") or default_config()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"no config at {path} (copy config.example.json to config.json "
                          f"in the install context, or set AGENT_REVIVE_CONFIG)")
    except (OSError, ValueError) as e:
        raise ConfigError(f"config at {path} cannot be read: {e}")
    recovery = cfg.get("recovery") if isinstance(cfg, dict) else None
    if not isinstance(recovery, dict):
        raise ConfigError(f"config at {path} has no 'recovery' block")
    if not recovery.get("mailbox"):
        raise ConfigError(f"config at {path} is missing required key 'recovery.mailbox'")
    return {"mailbox": recovery["mailbox"], "helper": GSHEETS}


def load_helper(path):
    """Import gsheets.py from PATH as the module `gsheets`, so its own lazy
    `import jwt` and its per-process caches behave exactly as they do under the
    CLI. Nothing from it is reimplemented here."""
    if "gsheets" in sys.modules:
        return sys.modules["gsheets"]
    if not os.path.isfile(path):
        raise ConfigError(f"the minting helper does not resolve to a file: {path} (the "
                          f"google-spreadsheet skill's gsheets.py, beside this skill in "
                          f"the fleet tree, is the minter this route reuses)")
    spec = importlib.util.spec_from_file_location("gsheets", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gsheets"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Reading a message
# --------------------------------------------------------------------------

def _header(msg, name):
    for h in (msg.get("payload") or {}).get("headers") or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def is_from_google(msg):
    sender = _header(msg, "From").lower()
    return any(s in sender for s in SENDERS)


def _decode(data):
    if not data:
        return ""
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _parts(part):
    yield part
    for child in part.get("parts") or []:
        yield from _parts(child)


def message_text(msg):
    """Subject, snippet, and every text part, as one searchable string. HTML
    parts are stripped to their text so a code wrapped in a <b> tag is found."""
    pieces = [_header(msg, "Subject"), str(msg.get("snippet", ""))]
    for part in _parts(msg.get("payload") or {}):
        body = (part.get("body") or {}).get("data")
        text = _decode(body)
        if not text:
            continue
        if "html" in str(part.get("mimeType", "")).lower():
            text = re.sub(r"<[^>]+>", " ", text)
        pieces.append(html.unescape(text))
    return "\n".join(p for p in pieces if p)


def extract_code(text):
    """The verification code in TEXT, or None. Phrase-anchored first; a bare
    6-digit group only when it is the ONLY one in the text."""
    for pattern in _PHRASED:
        m = pattern.search(text)
        if m:
            return m.group(1)
    bare = sorted(set(_BARE.findall(text)))
    if len(bare) == 1:
        return bare[0]
    return None


def newest_code(messages, now_ms, window_minutes):
    """The code from the newest Google message within the window, and that
    message's id. Raises NoCode with the reason otherwise."""
    cutoff = now_ms - window_minutes * 60 * 1000
    fresh = []
    for msg in messages:
        try:
            when = int(msg.get("internalDate", 0))
        except (TypeError, ValueError):
            when = 0
        if is_from_google(msg) and when >= cutoff:
            fresh.append((when, msg))
    if not fresh:
        raise NoCode(f"no message from {' or '.join(SENDERS)} in the last "
                     f"{window_minutes} min ({len(messages)} listed)")
    fresh.sort(key=lambda pair: pair[0], reverse=True)
    for when, msg in fresh:
        code = extract_code(message_text(msg))
        if code:
            return code, msg.get("id", "")
    raise NoCode(f"{len(fresh)} message(s) from Google in the last {window_minutes} min, "
                 f"none carrying a recognisable 6-digit code (newest: "
                 f"'{_header(fresh[0][1], 'Subject')}')")


# --------------------------------------------------------------------------
# The API calls, through the helper
# --------------------------------------------------------------------------

def fetch_messages(gs, mailbox):
    """List the candidate messages as MAILBOX and fetch each one in full."""
    listed = gs.call(GMAIL_BASE + "/messages", GMAIL_READONLY, subject=mailbox,
                     params={"q": LIST_QUERY, "maxResults": LIST_MAX})
    out = []
    for stub in listed.get("messages") or []:
        out.append(gs.call(f"{GMAIL_BASE}/messages/{stub['id']}", GMAIL_READONLY,
                           subject=mailbox, params={"format": "full"}))
    return out


def build_parser():
    p = argparse.ArgumentParser(description="print the newest Google verification code "
                                            "from the recovery mailbox")
    p.add_argument("--minutes", type=int, default=10,
                   help="how far back a code still counts (default 10)")
    p.add_argument("--config", help="agent-revive config.json (default: $AGENT_REVIVE_CONFIG, "
                                    "else the install context's copy)")
    return p


def main(argv=None, now_ms=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        gs = load_helper(cfg["helper"])
    except ConfigError as e:
        print(f"read_recovery_code: {e}", file=sys.stderr)
        return 2
    try:
        messages = fetch_messages(gs, cfg["mailbox"])
    except gs.MintError as e:
        print(f"read_recovery_code: mint refused for {cfg['mailbox']}: {e}", file=sys.stderr)
        return 3
    except (gs.CredentialError, gs.ConfigError) as e:
        print(f"read_recovery_code: {e}", file=sys.stderr)
        return 2
    except gs.ApiError as e:
        print(f"read_recovery_code: Gmail API: {e}", file=sys.stderr)
        return 4
    try:
        code, msg_id = newest_code(messages, now_ms or int(time.time() * 1000), args.minutes)
    except NoCode as e:
        print(f"read_recovery_code: {e}", file=sys.stderr)
        return 1
    print(f"read_recovery_code: code read from message {msg_id} in {cfg['mailbox']}",
          file=sys.stderr)
    print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
