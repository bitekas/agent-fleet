#!/usr/bin/env python3
"""Claim a chat request, so that exactly ONE agent acts on it.

    claim.py take     <conversation> <message> --agent <name> [--transport <t>]
    claim.py show     <conversation> <message> [--transport <t>]
    claim.py release  <conversation> <message> --agent <name> [--transport <t>]
    claim.py takeover <conversation> <message> --agent <name> --from <owner> [--transport <t>]
    claim.py prune    [--older-than DAYS]

    every verb also takes --dir <path>: FOR TESTS ONLY (see "the directory")

<conversation> is the conversation ID, never its name (for Slack C..., G...,
D...); <message> is the id of the message that carries the request (for Slack,
its `ts`). Both are validated against the transport's descriptor, `ids.conversation`
and `ids.message` in `<transport skill>/transport.json`. --transport names the
transport (`slack`) and defaults to the install's `transports.default`. The
policy - when to claim, what to do on each answer, when a takeover is allowed -
is SKILL.md's "Claiming a request". This header is the contract of the script.

EXIT CODES - four, and only the first two are an answer:

    0  won / ok           take: CLAIMED or ALREADY-YOURS; show: claimed;
                          release: released; takeover: took over; prune: done
    1  lost / not owner / unclaimed - ALWAYS with its result line on stdout,
       `CLAIMED-BY <owner> at <time>` or `UNCLAIMED`
    2  usage or invalid input - NOTHING was written anywhere
    3  environment fault - the claims directory is missing, unwritable, holds
       something that is not a claim, the fleet's settings or transport
       registry cannot be read, or the script itself crashed

⚠️ A 2 OR A 3 IS NOT A WIN AND NOT A LOSS. Read as a win, two agents act; read
as a loss, every agent stays out and the request is answered by nobody, which
looks exactly like a quiet channel. That is also why EVERY unexpected exception
is mapped to 3 in main(): Python's own exit status for an uncaught exception is
1, which is this script's "lost", so a crash would otherwise tell every agent to
stay silent. Do not narrow main()'s catch. The same holds for a result line
that cannot be written (stdout a closed pipe): after a WIN that would exit 1,
or 120 from the interpreter's own exit-time flush, while this agent holds the
claim - so it is exit 3, with the outcome repeated on stderr.

⚠️ EXIT 1 with no `CLAIMED-BY` or `UNCLAIMED` line IS NOT A LOSS - IT IS A FAULT,
handled exactly like 3. Exit 1 is also Python's own status when this script
could not run at all - a SyntaxError in a truncated or conflict-marked claim.py
in a mid-merge worktree, an import that fails - and that 1 arrives with a
traceback on stderr and nothing on stdout. Read as "lost", it would make that
agent stay out of every request, silently. The codes stay as they are; the
result line is what makes a 1 an answer.

Outcomes (0 and 1) print ONE line to stdout; a 2 or a 3 prints to stderr.

THE DIRECTORY. `claims_dir` in the host settings file (host.json, read through
fleetlib.paths.host()) - ONE file that every agent on the host reads, never a
per-agent config. A claims directory with more than one source is two claim
spaces: two agents each win the same request in their own directory and both
answer. For the same reason the value gets `~` expansion and nothing else: an
environment variable in it would resolve per agent service, which is a
per-agent directory by another route. (fleetlib honours FLEET_HOST_CONFIG so the
tests can point it at a fixture; nothing on a host sets it.) It must resolve to
an ABSOLUTE path (a relative one would differ per working directory: the same
split again), and it is NEVER created here. A missing directory is exit 3
naming the `fleet install` that creates it, because a mis-pointed path that
resolved silently into a fresh directory would be exactly that split, and
nobody would see it. slack-communication's installation/check verifies the
directory (owner, mode 700, a real link-and-unlink inside it) through
configured_dir() below.

`--dir` points every verb at another directory and exists for the tests, which
must never touch the real one. An agent that passes it to a live request has
left the fleet's claim space.

CLAIM NAMES. A Slack claim is named `<conversation>-<message>`, byte for byte
the name the Slack-only version of this script wrote, so the two versions share
one claim space while agents move from one to the other: either version's take
sees the other's claim, and neither can win a request the other holds. Every
other transport's claim is `<transport>--<conversation>-<message>`; Slack's
conversation alphabet has no lowercase letter, so the two forms never collide,
and each splits back unambiguously. `prune` recognises both forms, for every
transport in the registry, and deletes nothing else.

WHY `take` CANNOT LOSE A RACE IT SHOULD WIN, OR WIN ONE IT SHOULD LOSE. The
whole claim is written to a temp file in the claims directory, flushed and
fsynced, and then `os.link(tmp, final)` publishes it. link(2) is atomic and
refuses an existing name, so exactly one of any number of concurrent takers
creates the file, and the file never exists empty or half-written - a reader
either sees no claim or a complete one. The tempting `if not exists: open(w)`
lets every taker that checks before the first one writes win; claim.test.py
runs that version - with a widening sleep and without one - through the same
race harness as its NEGATIVE CONTROLS and requires more than one winner.
`take` takes no lock: the link is the primitive, so `take` can never block
behind another process (the lazy prune's lock is non-blocking, below).

`release`, `takeover` and `prune` change or delete an EXISTING file, so they
serialize on an flock of <dir>/.lock (bounded wait, then exit 3, never a hang).
`takeover` is a compare-and-swap: it succeeds only when the current owner is
--from, and writes the new claim to a temp file it then os.replace()s over the
old one, so the name never disappears and a concurrent `take` never sees a gap.
Its PRECONDITION - the owner's session is down - is policy SKILL.md states;
this script does not check it and cannot.

PRUNING is automatic and lazy: after `take` has printed its result it prunes at
most once per 24 h, gated on the mtime of <dir>/.last-prune (a stamp dated in the
future counts as stale; one that is not a regular file is refused, never opened
blocking), under a NON-blocking flock (busy: skip). It is best-effort: an error
is one stderr line and never changes take's exit code or its stdout line. The
directory grows exactly when agents claim, so the claim path is the one place a
prune is guaranteed to run. `prune` deletes only regular files (lstat, never
followed, never recursed) whose name is a claim name and whose mtime is older
than RETENTION_DAYS (14), plus this script's own leftover temp files older than
an hour.

AGE IS THE MTIME, so an ALREADY-YOURS refreshes it: otherwise a claim older than
the retention, re-taken by its owner, is deleted by that same take's lazy prune
and the next agent wins it. Two limits are stated rather than engineered
around: a forward clock jump of at least the retention ages every claim at once,
and an owner's re-take that lands between another process's prune deciding a
claim is old and deleting it can still lose that claim.

Input is validated before any path is built (re.fullmatch, never re.match with
`$`, which also matches before a trailing newline), against the descriptor's
patterns and AGENT_PAT below - and, under every descriptor pattern, against
SAFE_ID, which this file owns. A descriptor is another skill's file; SAFE_ID is
what keeps `../x` and `C1/../y` from naming a file outside the directory, and an
oversized value a 2 rather than a name the filesystem refuses, whatever pattern a
transport declares.

Stdlib plus the fleet's own lib/ (fleetlib, for host.json and the transport
registry). Run from any working directory: every path is anchored to this file,
to host.json or to the claims directory.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import math
import os
import re
import secrets
import stat
import sys
import time
from datetime import datetime, timezone
from typing import Optional

# The fleet root, from the REAL path: through a personal skill link `abspath`
# would name the agent's config directory, and three levels up from there is not
# the fleet tree (fleetlib's own rule).
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__)))))

AGENT_PAT = r"[a-z][a-z0-9_-]{0,31}"
AGENT_RE = re.compile(AGENT_PAT)
# The floor under every descriptor pattern (see the header): one path component
# made of id characters, an optional leading minus (a negative chat id), never
# `.` first, at most 64 characters. With the agent's 32 and the longest
# transport prefix, the longest name built here stays far below NAME_MAX.
SAFE_ID = re.compile(r"-?[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# The one transport whose claims carry no prefix (see CLAIM NAMES).
UNPREFIXED_TRANSPORT = "slack"

LOCK_NAME = ".lock"
STAMP_NAME = ".last-prune"
RETENTION_DAYS = 14
LAZY_PRUNE_EVERY_SECS = 24 * 3600
TMP_MAX_AGE_SECS = 3600
LOCK_WAIT_SECS = 30.0
# A take whose link lost to a file that vanished before it could be read (a
# release or a prune in between) tries again; bounded so a pathological
# directory cannot spin it.
TAKE_ATTEMPTS = 5
MAX_CLAIM_BYTES = 4096


class Invalid(Exception):
    """Bad input: exit 2, nothing written."""


class Fault(Exception):
    """The environment is wrong: exit 3."""


class Result:
    def __init__(self, code: int, line: str):
        self.code = code
        self.line = line

    def __repr__(self) -> str:
        return f"Result({self.code}, {self.line!r})"


# --- the fleet: host settings and the transport registry ----------------------

def _fleetlib():
    if os.path.join(FLEET_ROOT, "lib") not in sys.path:
        sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
    try:
        import fleetlib  # noqa: PLC0415 - imported late, so a broken lib is a 3, not a traceback
        from fleetlib import manifest, paths, transports  # noqa: F401,PLC0415
    except Exception as e:  # noqa: BLE001
        raise Fault(f"FLEETLIB cannot be imported from {FLEET_ROOT}/lib ({type(e).__name__}: {e})")
    return fleetlib


def _call(what: str, fn, *args):
    """Run a fleetlib call; anything it raises - SystemExit included - is a 3."""
    try:
        return fn(*args)
    except BaseException as e:  # noqa: BLE001 - KeyboardInterrupt aside, nothing here is an answer
        if isinstance(e, KeyboardInterrupt):
            raise
        raise Fault(f"{what}: {type(e).__name__}: {e}")


def configured_dir() -> str:
    """`claims_dir` from host.json, `~`-expanded, absolute.

    slack-communication's installation/check resolves the directory through THIS
    function, so the check and the script cannot disagree about which directory
    is the fleet's."""
    fl = _fleetlib()
    host = _call("HOST SETTINGS unreadable", fl.paths.host)
    raw = host.get("claims_dir") if isinstance(host, dict) else None
    if not isinstance(raw, str) or not raw:
        raise Fault("HOST SETTINGS have no 'claims_dir' - re-run `fleet install`")
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        raise Fault(f"HOST SETTINGS: claims_dir {raw!r} does not resolve to an absolute "
                    f"path, so it would differ per working directory")
    return os.path.normpath(path)


def require_dir(path: str) -> str:
    """The claims directory, which must already exist. Never created here."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise Fault(f"NO CLAIMS DIR {path} - `fleet install --agents-root {os.path.dirname(path)}` creates it")
    except OSError as e:
        raise Fault(f"CLAIMS DIR {path} cannot be reached ({errno.errorcode.get(e.errno, e.errno)}: "
                    f"{e.strerror})")
    if not stat.S_ISDIR(st.st_mode):
        raise Fault(f"CLAIMS DIR {path} is not a directory - remove what is there, then: "
                    f"fleet install --agents-root {os.path.dirname(path)}")
    return path


def _body(pattern: str) -> str:
    """A descriptor pattern without its ^ and $ anchors, for composing names."""
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1]
    return pattern


class Transport:
    """One transport's claim naming, built from its descriptor."""

    def __init__(self, desc: dict):
        try:
            self.name = desc["name"]
            self.conv_pat = _body(desc["ids"]["conversation"])
            self.msg_pat = _body(desc["ids"]["message"])
            self.conv_re = re.compile(self.conv_pat)
            self.msg_re = re.compile(self.msg_pat)
        except (KeyError, TypeError, re.error) as e:
            raise Fault(f"TRANSPORT descriptor unusable ({type(e).__name__}: {e})")
        self.prefix = "" if self.name == UNPREFIXED_TRANSPORT else f"{self.name}--"
        # Non-capturing on purpose: these are composed into one alternation.
        self.name_pat = (re.escape(self.prefix) + "(?:" + self.conv_pat + ")-(?:" + self.msg_pat + ")")

    def claim_name(self, conversation: str, message: str) -> str:
        return f"{self.prefix}{conversation}-{message}"


def _descriptors() -> list:
    fl = _fleetlib()
    got = _call("TRANSPORT registry unreadable", fl.transports.all)
    descs = list(got.values()) if isinstance(got, dict) else list(got)
    if not descs:
        raise Fault("TRANSPORT registry is empty - no <skill>/transport.json in the fleet tree")
    return descs


def transport(name: Optional[str]) -> Transport:
    """The named transport, or the install's default when NAME is None."""
    if name is None:
        fl = _fleetlib()
        root = _call("NO DEFAULT TRANSPORT (no install manifest; pass --transport)",
                     fl.paths.install_root)
        m = _call("NO DEFAULT TRANSPORT (install manifest unreadable)", fl.manifest.load, root)
        try:
            name = m["transports"]["default"]
        except (KeyError, TypeError):
            raise Fault("NO DEFAULT TRANSPORT: the install manifest has no transports.default")
    for d in _descriptors():
        if isinstance(d, dict) and d.get("name") == name:
            return Transport(d)
    raise Invalid(f"INVALID --transport {name!r}: not a transport in this fleet tree "
                  f"(one of: {', '.join(sorted(str(d.get('name')) for d in _descriptors()))})")


def _name_patterns() -> tuple[re.Pattern, re.Pattern]:
    """(claim name, temp file name) patterns over EVERY registered transport."""
    alt = "|".join(Transport(d).name_pat for d in _descriptors())
    claim_re = re.compile("(?:" + alt + ")")
    # .<claim name>.<agent>.<pid>.<random>.tmp - a leading dot, so a temp file can
    # never match the claim pattern and be read as a claim.
    tmp_re = re.compile(r"\.(?:" + alt + r")\." + AGENT_PAT + r"\.[0-9]+\.[0-9a-f]+\.tmp")
    return claim_re, tmp_re


# --- validation ------------------------------------------------------------

def check_agent(agent: str, flag: str = "--agent") -> str:
    if not isinstance(agent, str) or not AGENT_RE.fullmatch(agent):
        raise Invalid(f"INVALID {flag} {agent!r}: must match {AGENT_PAT}")
    return agent


def claim_path(d: str, t: Transport, conversation: str, message: str) -> tuple[str, str]:
    if not isinstance(conversation, str) or not SAFE_ID.fullmatch(conversation) \
            or not t.conv_re.fullmatch(conversation):
        raise Invalid(f"INVALID conversation {conversation!r}: must be a {t.name} conversation ID "
                      f"matching {t.conv_pat}, never a channel name")
    if not isinstance(message, str) or not SAFE_ID.fullmatch(message) \
            or not t.msg_re.fullmatch(message):
        raise Invalid(f"INVALID message {message!r}: must be a {t.name} message id matching {t.msg_pat}")
    name = t.claim_name(conversation, message)
    return name, os.path.join(d, name)


# --- primitives ------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render(fields: list[tuple[str, str]]) -> bytes:
    return "".join(f"{k}: {v}\n" for k, v in fields).encode("utf-8")


def _write_tmp(d: str, name: str, agent: str, data: bytes) -> str:
    """Write DATA to a fresh temp file in D, flushed and fsynced. O_EXCL, so a
    name collision is an error rather than a silent overwrite."""
    tmp = os.path.join(d, f".{name}.{agent}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as e:
        raise Fault(f"CLAIMS DIR {d} cannot be written by this user "
                    f"({errno.errorcode.get(e.errno, e.errno)}: {e.strerror})")
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        _unlink_quiet(tmp)
        raise
    os.close(fd)
    return tmp


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def read_claim(path: str) -> Optional[dict]:
    """The claim at PATH as a dict, or None when there is none.

    O_NOFOLLOW: a symlink named like a claim is not a claim (it could name any
    file). O_NONBLOCK + S_ISREG: a FIFO there would otherwise block forever."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise Fault(f"CLAIM {path} is a symlink, not a claim - remove it by hand after reading it")
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Fault(f"CLAIM {path} is not a regular file - remove it by hand after reading it")
        raw = os.read(fd, MAX_CLAIM_BYTES)
    finally:
        os.close(fd)
    fields = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        k, sep, v = line.partition(": ")
        if sep:
            fields[k.strip()] = v.strip()
    if not AGENT_RE.fullmatch(fields.get("agent", "")) or not fields.get("claimed"):
        raise Fault(f"CLAIM {path} is malformed (no valid agent/claimed lines): {raw[:200]!r}")
    return fields


def _owner_line(rec: dict) -> str:
    line = f"CLAIMED-BY {rec['agent']} at {rec['claimed']}"
    if rec.get("took_over_from"):
        line += f" (took over from {rec['took_over_from']}, original claim {rec.get('original_claim', '?')})"
    return line


class _DirLock:
    """flock on <dir>/.lock. Blocking with a bounded wait by default; with
    blocking=False, `acquired` is False when another process holds it."""

    def __init__(self, d: str, blocking: bool = True):
        self.path = os.path.join(d, LOCK_NAME)
        self.blocking = blocking
        self.fd = None
        self.acquired = False

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + LOCK_WAIT_SECS
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except BlockingIOError:
                if not self.blocking:
                    return self
                if time.monotonic() >= deadline:
                    os.close(self.fd)
                    self.fd = None
                    finder = "lsof" if sys.platform == "darwin" else "fuser -v"
                    raise Fault(f"LOCK BUSY {self.path}: held for more than {LOCK_WAIT_SECS:.0f}s by "
                                f"another process - find it with: {finder} {self.path}")
                time.sleep(0.02)

    def __exit__(self, *exc):
        if self.fd is not None:
            if self.acquired:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
        return False


# --- verbs -----------------------------------------------------------------

def take(d: str, t: Transport, conversation: str, message: str, agent: str) -> Result:
    check_agent(agent)
    name, final = claim_path(d, t, conversation, message)
    when = utc_now()
    tmp = _write_tmp(d, name, agent, _render([("agent", agent), ("claimed", when)]))
    try:
        for _ in range(TAKE_ATTEMPTS):
            try:
                os.link(tmp, final)
                return Result(0, f"CLAIMED {final} by {agent} at {when}")
            except FileExistsError:
                pass
            except OSError as e:
                raise Fault(f"CLAIMS DIR {d}: link(2) refused ({errno.errorcode.get(e.errno, e.errno)}: "
                            f"{e.strerror}) - the claim's atomic primitive is unavailable here")
            rec = read_claim(final)
            if rec is None:
                continue  # released or pruned between our link and our read
            if rec["agent"] == agent:
                # Refresh the mtime: prune judges age by it, and without this the
                # lazy prune of this very take deletes the claim it just confirmed.
                try:
                    os.utime(final, follow_symlinks=False)
                except FileNotFoundError:
                    continue  # pruned between our read and our refresh: claim it afresh
                return Result(0, f"ALREADY-YOURS {final} by {agent} at {rec['claimed']}")
            return Result(1, _owner_line(rec))
        raise Fault(f"CLAIM {final} kept appearing and vanishing across {TAKE_ATTEMPTS} attempts")
    finally:
        _unlink_quiet(tmp)


def show(d: str, t: Transport, conversation: str, message: str) -> Result:
    _, final = claim_path(d, t, conversation, message)
    rec = read_claim(final)
    return Result(1, "UNCLAIMED") if rec is None else Result(0, _owner_line(rec))


def release(d: str, t: Transport, conversation: str, message: str, agent: str) -> Result:
    check_agent(agent)
    _, final = claim_path(d, t, conversation, message)
    with _DirLock(d):
        rec = read_claim(final)
        if rec is None:
            return Result(1, "UNCLAIMED")
        if rec["agent"] != agent:
            return Result(1, _owner_line(rec))
        os.unlink(final)
    return Result(0, f"RELEASED {final} by {agent}")


def takeover(d: str, t: Transport, conversation: str, message: str, agent: str, from_: str) -> Result:
    check_agent(agent)
    check_agent(from_, "--from")
    if agent == from_:
        raise Invalid(f"INVALID --from {from_!r}: equal to --agent; an owner re-takes its own "
                      f"claim with `take`, which answers ALREADY-YOURS")
    name, final = claim_path(d, t, conversation, message)
    with _DirLock(d):
        rec = read_claim(final)
        if rec is None:
            return Result(1, "UNCLAIMED")
        if rec["agent"] != from_:
            return Result(1, _owner_line(rec))
        when = utc_now()
        tmp = _write_tmp(d, name, agent, _render([
            ("agent", agent), ("claimed", when),
            # original_claim is the FIRST claim's time, carried through a chain.
            ("took_over_from", rec["agent"]),
            ("original_claim", rec.get("original_claim") or rec["claimed"])]))
        try:
            os.replace(tmp, final)
        except BaseException:
            _unlink_quiet(tmp)
            raise
    return Result(0, f"TOOK-OVER {final} by {agent} from {from_} at {when}")


def _prune_locked(d: str, days: float, now: float) -> int:
    claim_re, tmp_re = _name_patterns()
    n = 0
    for name in os.listdir(d):
        is_claim = claim_re.fullmatch(name) is not None
        is_tmp = not is_claim and tmp_re.fullmatch(name) is not None
        if not (is_claim or is_tmp):
            continue
        p = os.path.join(d, name)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue  # a symlink, a directory or a FIFO is never ours to delete
        limit = days * 86400 if is_claim else TMP_MAX_AGE_SECS
        if now - st.st_mtime > limit:
            try:
                os.unlink(p)
                n += 1
            except FileNotFoundError:
                pass
    return n


def check_days(days) -> float:
    # isfinite: `nan` compares False against every age, so it would prune nothing
    # while reporting PRUNED 0 as if the directory were clean.
    if isinstance(days, bool) or not isinstance(days, (int, float)) \
            or not math.isfinite(days) or days <= 0:
        raise Invalid(f"INVALID --older-than {days!r}: must be a positive, finite number of days")
    return float(days)


def prune(d: str, days: float) -> Result:
    days = check_days(days)
    with _DirLock(d):
        n = _prune_locked(d, float(days), time.time())
    return Result(0, f"PRUNED {n}")


def lazy_prune(d: str) -> None:
    """At most once per 24 h, never blocking, never raising: see the header."""
    try:
        stamp = os.path.join(d, STAMP_NAME)

        def due() -> bool:
            try:
                st = os.lstat(stamp)
            except FileNotFoundError:
                return True
            if not stat.S_ISREG(st.st_mode):
                raise Fault(f"{stamp} is not a regular file - remove it by hand")
            age = time.time() - st.st_mtime
            # A stamp dated in the FUTURE is stale, or it would disable the prune
            # until that date.
            return age >= LAZY_PRUNE_EVERY_SECS or age < 0

        if not due():
            return
        with _DirLock(d, blocking=False) as lock:
            if not lock.acquired or not due():
                return
            # The stamp moves BEFORE the prune itself, so a prune that fails while
            # running costs one attempt (and one stderr line) per day. A fault
            # BEFORE this point - an unusable lock or stamp - repeats on every
            # take, which is the point: somebody has to fix it.
            # O_NONBLOCK + S_ISREG: opening a FIFO for write with no reader would
            # block forever, and take must never block.
            fd = os.open(stamp, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise Fault(f"{stamp} is not a regular file - remove it by hand")
                os.utime(fd)
            finally:
                os.close(fd)
            _prune_locked(d, float(RETENTION_DAYS), time.time())
    except Exception as e:  # noqa: BLE001 - best-effort by contract
        print(f"claim.py: lazy prune skipped ({type(e).__name__}: {e}); the take result above stands",
              file=sys.stderr)


# --- CLI -------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claim.py", description="Claim a chat request (see the header).")
    sub = p.add_subparsers(dest="verb", required=True)

    def add(name, agent=False, key=True):
        s = sub.add_parser(name)
        if key:
            s.add_argument("conversation")
            s.add_argument("message")
            s.add_argument("--transport", default=None,
                           help="the transport's name; default: the install's transports.default")
        if agent:
            s.add_argument("--agent", required=True)
        s.add_argument("--dir", help="claims directory override - FOR TESTS ONLY")
        return s

    add("take", agent=True)
    add("show")
    add("release", agent=True)
    add("takeover", agent=True).add_argument("--from", dest="from_", required=True)
    add("prune", key=False).add_argument("--older-than", type=float, default=None)
    return p


def _resolve_dir(arg: Optional[str]) -> str:
    if arg is None:
        return require_dir(configured_dir())
    if not os.path.isabs(arg):
        raise Invalid(f"INVALID --dir {arg!r}: must be an absolute path")
    return require_dir(os.path.normpath(arg))


def main(argv: Optional[list] = None) -> int:
    args = _parser().parse_args(argv)  # a usage error exits 2 from here
    try:
        # Validate everything that names a file BEFORE resolving the directory,
        # so bad input is a 2 even on a machine whose directory is missing.
        t = None
        if args.verb != "prune":
            t = transport(args.transport)
            claim_path("/", t, args.conversation, args.message)
        if getattr(args, "agent", None) is not None:
            check_agent(args.agent)
        if args.verb == "takeover":
            check_agent(args.from_, "--from")
        if args.verb == "prune" and args.older_than is not None:
            check_days(args.older_than)
        d = _resolve_dir(args.dir)
        if args.verb == "take":
            r = take(d, t, args.conversation, args.message, args.agent)
        elif args.verb == "show":
            r = show(d, t, args.conversation, args.message)
        elif args.verb == "release":
            r = release(d, t, args.conversation, args.message, args.agent)
        elif args.verb == "takeover":
            r = takeover(d, t, args.conversation, args.message, args.agent, args.from_)
        else:
            r = prune(d, RETENTION_DAYS if args.older_than is None else args.older_than)
    except Invalid as e:
        print(e, file=sys.stderr)
        return 2
    except Fault as e:
        print(e, file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - see the header: a crash must never read as "lost"
        print(f"FAULT claim.py {args.verb}: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    try:
        print(r.line, flush=True)
    except Exception as e:  # noqa: BLE001 - a broken pipe after a WIN must not exit 1 ("lost")
        # stdout -> /dev/null as well: the interpreter re-flushes stdout at exit,
        # and a second failure there turns this 3 into exit 120.
        with contextlib.suppress(Exception):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        with contextlib.suppress(Exception):
            print(f"FAULT claim.py {args.verb}: the result line could not be written "
                  f"({type(e).__name__}: {e}); the outcome was: {r.line}", file=sys.stderr)
        return 3
    if args.verb == "take":
        lazy_prune(d)
    return r.code


if __name__ == "__main__":
    sys.exit(main())
