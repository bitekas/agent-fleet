#!/usr/bin/env python3
"""Task scheduler - the clock behind the agent fleet's scheduled work.

Evaluates every active task's schedule predicate once a second and prints ONE LINE
per task that has come due. It runs as a supervised service, and the session follows
its output under a Claude Code persistent Monitor: each printed line is injected into
the agent's session as a wake-up event, which is how a scheduled task reaches the agent
at all. There is no other IPC. The daemon never does the work - it only says when.

Mechanics (the predicate contract, the CLI, this line format) live in SKILL.md beside
this file. Policy (who may schedule what, and what a due task may do unattended) lives
in the owning agent's charter, which SKILL.md names - this script deliberately does NOT
filter, so that charter is the only enforcement point.

Schedules are PREDICATES, not cron lines. Each task carries a small Python snippet
defining `should_fire(now, state)`, evaluated every tick with the current epoch and the
dict it returned last time. That is what lets a schedule say "twice a day, except in
leap years, and not on the second Monday" - no cron dialect can, and the thing that
understands the sentence is the thing that writes the snippet.

⚠️ COALESCING IS A PROPERTY OF THE PREDICATE, NOT OF THIS DAEMON. The loop never
replays a missed tick; it evaluates once per tick against the current time. A predicate
written against the newest due instant that has passed (the template, via due_slots())
fires ONCE after an outage and reports how many it folded in. A predicate written as
`local(now).hour == 9` fires ZERO times after an outage and says nothing about it.
Both look identical from outside, which is why the template is load-bearing.

EVERY TASK ROW CARRIES WHO ASKED AND WHY, and `add` refuses without the why. The
requester is stored as a name a human recognises (a chat user id is resolved through
the requester directory, and an unresolvable one is refused rather than stored); the
reason answers why the task is there at all, why it was added and what problem it
solves. Both ride the wake-up line, reason first - see format_emit for why that order
is load-bearing. The alternative is a database of schedules nobody dares cancel because
nobody remembers what any of them are for.

`set-meta` is the one verb that rewrites those two fields, and it stamps
`meta_updated_by`/`meta_updated_at` when it does - a separate pair from `updated_at`,
which the daemon bumps on every state change and fire. `audit --baseline <file>` hashes
the instruction, the predicate (both its source and the sha the code cache is keyed on),
the requester and the reason per ACTIVE task - WHAT the agent does, WHEN it does it, and
who asked for it - and reports CHANGED/NEW/GONE against that file, saying for each
difference whether a `set-meta` since the baseline could account for it: a backfill and a
write that went around sched.py entirely look identical without that.

ORIGINS ARE TRANSPORT PLUS KIND. An origin says where the answer goes: `session`, or
`<transport>:<kind>:<conversation>[:<thread>]` on one of the fleet's WORKING chat
transports (the registry fleetlib reads from each transport skill's transport.json),
with the forms `slack:<id>` and `dm:<id>` accepted forever. A database created by this
version stores (origin_kind, origin_transport); a database created before it - no
`origin_transport` column - is never altered, keeps the Slack-only vocabulary
(`slack_channel`, `slack_dm`, `slack_thread`, `session`) and refuses any other
transport. decode_origin() is the one reader of both.

Usage (<skill dir> is the directory holding this file):
  <skill dir>/sched.py                      # tick loop (run as a service)
  <skill dir>/sched.py --once               # single tick (smoke test)
  <skill dir>/sched.py simulate ...         # dry-run a predicate
  <skill dir>/sched.py doctor               # resolved config + DB health
  <skill dir>/sched.py audit --baseline F   # provenance drift
  python3 <skill dir>/sched.test.py         # offline regression guard

Is it armed?  pgrep -af "[s]cheduled-tasks/sched.py"     (macOS: pgrep -fl)

State (tasks, their carried predicate state, and every run's outcome) lives in ONE
SQLite file at db.path from the config SCHED_CONFIG names, WAL mode, mode 0600, with
the single-instance lock beside it.
⚠️ The DB path comes from the CONFIG this process resolved, and the lock lives beside
the DB, so two daemons sharing one config cannot both run. SCHED_DB overrides the path
for a one-off and is NOT how a deployment is configured: a launcher that exports
SCHED_DB or SCHED_CONFIG inconsistently produces a second daemon writing a second
database and firing every task twice, and nothing reports it.
⚠️ Deleting the DB does NOT stop the schedules - it silently restarts every one of them
from an empty state: each task re-arms on its next evaluation and fires nothing until
its next due time, so a daily job quietly skips a day. Use `cancel`, never `rm`.
⚠️ A predicate is CODE RUN IN THIS PROCESS. The AST allow-list, the emptied builtins
and the interval timer stop mistakes and runaway loops. They are NOT a security
boundary - no in-process CPython sandbox survives a determined author. That is
acceptable only because the owning agent writes every predicate and the DB is 0600 in
its own home. If a predicate ever originates anywhere else, move evaluation into a
forked child with setrlimit BEFORE that happens, not after.

An idle scheduler writes nothing: state is persisted only when a predicate's state
actually changes, when a task fires, or when one errors.

Configuration: nothing deployment- or person-specific is hardcoded here. It all lives
in the config file SCHED_CONFIG names (copied from config.example.json); required keys
are fatal when missing and name themselves. Point SCHED_CONFIG at another copy to run a
second, independent scheduler. Requires only the standard library, plus the fleet's
own fleetlib (read for the transport registry by `add` and `set-meta`, never by the
tick loop).
"""

import argparse
import ast
import calendar
import contextlib
import copy
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import types
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = os.environ.get(
    "SCHED_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
)
_REQUIRED = object()


def _load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"SCHED-CONFIG missing config file: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"SCHED-CONFIG {path}: not valid JSON - {e}")


CONFIG = _load_config(CONFIG_FILE)


def cfg(dotted: str, default=_REQUIRED):
    """Read a dotted key out of CONFIG.

    A missing REQUIRED key exits loudly naming the key, rather than defaulting.
    Silently defaulting an identity or location value is how a scheduler ends up
    reading an empty database or answering to the wrong owner - failures that look
    like "nothing was due today" rather than like a broken config.
    """
    node = CONFIG
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is _REQUIRED:
                sys.exit(f"SCHED-CONFIG {CONFIG_FILE}: missing required key '{dotted}'")
            return default
        node = node[part]
    return node


def _strip_comments(d: dict) -> dict:
    """Drop the _comment keys config.json uses for documentation (JSON has no comment
    syntax), so they can never be mistaken for data."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


OWNER_CONFIG_DIR = cfg("owner.claude_config_dir")
DB_PATH = os.path.expanduser(os.environ.get("SCHED_DB", cfg("db.path")))
LOCK_FILE = DB_PATH + ".lock"
BUSY_TIMEOUT_SECS = float(cfg("db.busy_timeout_secs", default=5))

DEFAULT_TZ = cfg("defaults.tz")

TICK_SECS = float(os.environ.get("SCHED_TICK_SECS", cfg("loop.tick_secs", default=1.0)))
MAX_ACTIVE_TASKS = int(cfg("loop.max_active_tasks", default=200))
MAX_FIRES_PER_TICK = int(cfg("loop.max_fires_per_tick", default=5))
RESYNC_LAG_SECS = float(cfg("loop.resync_lag_secs", default=30))

EVAL_TIMEOUT_SECS = float(
    os.environ.get("SCHED_EVAL_TIMEOUT_SECS", cfg("eval.timeout_secs", default=0.25))
)
MAX_ERRORS = int(cfg("eval.max_errors", default=3))
MAX_DUE_SLOTS = int(cfg("eval.max_due_slots", default=4096))
MAX_LOOKBACK_DAYS = 400

MAX_LINE_CHARS = int(cfg("emit.max_line_chars", default=1200))
TITLE_CHARS = int(cfg("emit.title_chars", default=60))
MIN_INTERVAL_SECS = float(cfg("emit.min_interval_secs", default=30))
REPLAY_GRACE_SECS = float(cfg("emit.replay_grace_secs", default=120))
REPLAY_MAX = int(cfg("emit.replay_max", default=10))
ALERT_MIN_INTERVAL_SECS = float(cfg("emit.alert_min_interval_secs", default=3600))
MAX_REPLAYS_PER_RUN = 3

REASON_CHARS = int(cfg("emit.reason_chars", default=400))
REQUESTER_CHARS = int(cfg("emit.requester_chars", default=40))

# The requester directory turns an id into the human name a reader recognises. Both
# keys default to None, i.e. no directory: an install with no chat roster stores
# whatever `--requester` was given, and resolve_requester() below refuses an id-shaped
# value rather than storing one nobody can read.
REQUESTER_DIRECTORY_FILE = cfg("requester.directory_file", default=None)
REQUESTER_DIRECTORY_KEY = cfg("requester.directory_key", default=None)
# None means "derive it": the alternation of every working transport's `ids.user`
# (requester_id_pattern()), so the scheduler recognises a user id from whichever chat
# transports this fleet runs instead of hard-coding one vendor's shape.
REQUESTER_ID_PATTERN = cfg("requester.id_pattern", default=None)

ADD_SIMULATE_DAYS = int(cfg("add.simulate_days", default=7))
FIRES_PER_DAY_WARN = float(cfg("add.fires_per_day_warn", default=24))

AUTO_ARCHIVE_DAYS = int(cfg("retention.auto_archive_days", default=30))
RUNS_PER_TASK = int(cfg("retention.runs_per_task", default=50))
PURGE_DAYS = int(cfg("retention.purge_days", default=180))

CODE_CACHE_MAX = 256
DB_FATAL_STRIKES = 5

LIVE_STATUSES = ("active", "paused")
TERMINAL_STATUSES = ("done", "cancelled", "failed", "archived")

# ---------------------------------------------------------------------------
# Logging - stderr only. The ONLY stdout writers are emit lines and the CLI.
# ---------------------------------------------------------------------------


def log_info(msg: str, latch: dict | None = None, key: str = "logged") -> None:
    """Degraded-but-running note. Pass a latch dict to log it once, not once per tick -
    a message repeated every second is a message nobody reads."""
    if latch is not None:
        if latch.get(key):
            return
        latch[key] = True
    print(f"SCHED-INFO {msg}", file=sys.stderr, flush=True)


def log_error(scope: str, e: BaseException) -> None:
    print(f"SCHED-ERROR {scope} {type(e).__name__}: {e}", file=sys.stderr, flush=True)


_alert_state: dict = {}


def emit_alert(msg: str, now: float) -> None:
    """One rate-limited stdout line for a condition that stops the whole scheduler.

    A deliberate exception to "only due-task lines reach stdout". A silently dead
    scheduler is this system's worst failure - tasks stop firing and nobody notices
    until someone asks about a report that quietly stopped arriving. The obvious
    alternative, a scheduled health check, is circular.
    """
    if now - _alert_state.get("last", 0) < ALERT_MIN_INTERVAL_SECS:
        return
    _alert_state["last"] = now
    print(f"SCHED alert {collapse(msg)}", flush=True)


def collapse(text: str) -> str:
    return " ".join((text or "").split())


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def acquire_singleton_lock():
    """Owning-agent + single-instance guards (both exit 0 so a Monitor just ends).

    Only the agent whose CLAUDE_CONFIG_DIR matches config's owner.claude_config_dir
    owns the schedule; every other agent refuses here, so the whole fleet can share one
    "arm at session start" rule without two daemons firing every task twice. The flock
    catches the rest - a leftover daemon from a crashed session, a concurrent manual
    run. Returns the held fd; keep it referenced for process lifetime.
    """
    caller_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    owner = os.path.realpath(os.path.expanduser(OWNER_CONFIG_DIR))
    if not caller_dir or os.path.realpath(caller_dir) != owner:
        print(
            f"SCHED-GUARD not the owning agent "
            f"(CLAUDE_CONFIG_DIR={caller_dir or '<unset>'}, owner={OWNER_CONFIG_DIR}); not scheduling",
            file=sys.stderr, flush=True,
        )
        sys.exit(0)
    os.makedirs(os.path.dirname(LOCK_FILE), mode=0o700, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("SCHED-GUARD another scheduler already holds the lock; not scheduling",
              file=sys.stderr, flush=True)
        sys.exit(0)
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

# Columns a database made by an older copy of this script lacks: _ensure_columns()
# below adds them to an existing database, and SCHEMA above carries them for a fresh
# one.
#
# ⚠️ ADDING A COLUMN DOES NOT BUMP SCHEMA_VERSION, AND THAT IS THE POINT. A bump makes
# every older running copy of this script exit on sight of the database ("schema
# vN is newer than this script"), and a daemon is a long-lived process that a code
# update does not restart - so the agent whose scheduler you were improving stops
# firing until someone notices and restarts it. An additive, NULLABLE column is
# invisible to the running code instead: it reads `SELECT *`, gets one extra key, and
# names every column it writes. Reserve the version bump for a change that genuinely
# breaks the old reader (a dropped or retyped column), where refusing IS the right
# behaviour.
ADDED_COLUMNS = (
    # Why the task exists at all, in the requester's terms: what problem it solves and
    # what was happening when it was asked for. `add` REFUSES without one. A schedule
    # outlives the conversation that created it by months, and the row is all the
    # future reader gets - without this field the only honest answer to "can we drop
    # this task?" is "nobody knows", which is how a task nobody understands keeps
    # firing forever.
    ("reason", "TEXT"),
    # WHO last rewrote requester_uid/reason with `set-meta`, and WHEN. `set-meta` is the
    # one verb built to write provenance, and without these columns it is the one write
    # that leaves no trace: a requester or a reason can be replaced and `show`, `list`,
    # the wake-up line and any instruction-hash baseline all read unchanged.
    #
    # ⚠️ THEY ARE NOT `updated_by`/`updated_at`, AND THE PREFIX IS LOAD-BEARING.
    # `updated_at` already exists and is the DAEMON's: _write_state, _record_eval_error,
    # _commit_fire, _finish and auto_archive all set it, so it moves on every state
    # change, every fire and every predicate error. A plain `updated_by` sitting beside
    # it would be read as a pair - "Bea, three minutes ago" - on a row whose timestamp
    # the daemon bumped three minutes ago and whose reason Bea last touched in March.
    # A separate timestamp, written only by set-meta, is the only one that can answer
    # "when was this row's provenance last rewritten". Renaming the daemon's column
    # instead is not an option: a running daemon names `updated_at` in five UPDATE
    # statements and a code update does not restart it.
    ("meta_updated_by", "TEXT"),
    ("meta_updated_at", "INTEGER"),
    # ⚠️ `origin_transport` IS DELIBERATELY NOT HERE, AND MUST NEVER BE. Its absence is
    # how a database created before transport-neutral origins is recognised
    # (is_legacy()), and such a database keeps its Slack-only CHECK on origin_kind -
    # SQLite cannot rewrite a CHECK in place. Added here, the column would appear on
    # every live database, every legacy database would then read as fresh, and the next
    # `add` would write `channel` into a column whose CHECK admits only `slack_channel`:
    # an IntegrityError on the live scheduler and nowhere else. It exists only in SCHEMA,
    # for a database this version creates. sched.test.py section 16 pins it.
)

# THE TWO STORED ORIGIN FORMATS, and why the user_version stays 1 for both.
#
# A database created by this SCHEMA stores (origin_kind, origin_transport) with
# origin_kind in channel|dm|thread|session and origin_transport NULL exactly for
# session - the CHECK below. A database created before it (no origin_transport column)
# stores Slack origins as slack_channel|slack_dm|slack_thread and is never altered.
# decode_origin() reads both. The version is not bumped for the fresh format, because
# the reader of an older copy of this script is not broken by it - it reads, lists and
# fires a fresh database unchanged; only its `add` is refused, by the CHECK, loudly and
# while a person is present. A bump would instead stop an older daemon at start.
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id              TEXT    PRIMARY KEY,
  rev             INTEGER NOT NULL DEFAULT 1,
  title           TEXT    NOT NULL,
  instruction     TEXT    NOT NULL,
  predicate_src   TEXT    NOT NULL,
  predicate_sha   TEXT    NOT NULL,
  tz              TEXT    NOT NULL,
  status          TEXT    NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','paused','done','cancelled','failed','archived')),
  state_json      TEXT    NOT NULL DEFAULT '{}',
  origin_kind     TEXT    NOT NULL
                  CHECK (origin_kind IN ('channel','dm','thread','session')),
  origin_transport TEXT
                  CHECK ((origin_kind = 'session') = (origin_transport IS NULL)),
  origin_id       TEXT    NOT NULL,
  origin_thread   TEXT,
  origin_label    TEXT,
  requester_uid   TEXT    NOT NULL,   -- the requester's HUMAN-READABLE identity
  reason          TEXT,               -- why this task exists (see ADDED_COLUMNS)
  meta_updated_by TEXT,               -- who last rewrote requester/reason (set-meta)
  meta_updated_at INTEGER,            -- and when - NOT updated_at, which is the daemon's
  not_before      INTEGER,
  not_after       INTEGER,
  max_fires       INTEGER,
  min_interval    REAL,
  last_eval_at    INTEGER,
  last_fire_at    INTEGER,
  fire_count      INTEGER NOT NULL DEFAULT 0,
  error_count     INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT,
  created_at      INTEGER NOT NULL,
  created_by      TEXT    NOT NULL DEFAULT 'agent',
  updated_at      INTEGER NOT NULL,
  finished_at     INTEGER,
  finished_reason TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS tasks_live     ON tasks(status, not_before);
CREATE INDEX IF NOT EXISTS tasks_finished ON tasks(finished_at) WHERE finished_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS tasks_origin   ON tasks(origin_id, status);

CREATE TABLE IF NOT EXISTS runs (
  run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id      TEXT    NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  fired_at     INTEGER NOT NULL,
  missed       INTEGER NOT NULL DEFAULT 0,
  replays      INTEGER NOT NULL DEFAULT 0,
  emitted_line TEXT    NOT NULL,
  status       TEXT    NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','ok','failed','skipped','lost')),
  started_at   INTEGER,
  finished_at  INTEGER,
  outcome      TEXT,
  UNIQUE(task_id, fired_at)
) STRICT;

CREATE INDEX IF NOT EXISTS runs_by_task ON runs(task_id, fired_at DESC);
CREATE INDEX IF NOT EXISTS runs_pending ON runs(status) WHERE status = 'pending';
"""


def connect(path: str = None, *, readonly: bool = False) -> sqlite3.Connection:
    """Open the task DB with the pragmas both writers depend on.

    WAL is what lets the daemon read a consistent snapshot every tick while the CLI
    writes; busy_timeout turns the resulting contention into a short wait instead of an
    exception. isolation_level=None puts us in autocommit, so every transaction in this
    file is an explicit BEGIN IMMEDIATE - a DEFERRED transaction that starts by reading
    and later writes can fail to upgrade at COMMIT even with busy_timeout set, and that
    failure would land on the fire path, where it costs a wake-up.
    """
    path = path or DB_PATH
    if not readonly:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    mode = "ro" if readonly else "rwc"
    conn = sqlite3.connect(f"file:{path}?mode={mode}", uri=True,
                           timeout=BUSY_TIMEOUT_SECS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_SECS * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add any ADDED_COLUMNS the tasks table does not have yet.

    Guarded by PRAGMA table_info rather than by a version number, so it is idempotent,
    order-independent and safe to run against a database another process is using: each
    ALTER is a short write that WAL + busy_timeout turn into a wait, and the daemon
    holding that database keeps running because the column is additive and nullable
    (see ADDED_COLUMNS for why this is not a user_version bump).
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    for name, decl in ADDED_COLUMNS:
        if name not in have:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                # The read and the ALTER are separate statements, so two processes can
                # both see the column missing and the second one gets "duplicate column
                # name". The window is microseconds and it is one-shot per column - but
                # the choreography that opens it is exactly the rollout (restart the
                # daemon, immediately run a CLI verb to backfill), and out of the daemon
                # an unhandled one means the daemon does not START, which looks like a
                # day with nothing due. Losing the race is success: re-read and confirm.
                if name not in {r["name"] for r in
                                conn.execute("PRAGMA table_info(tasks)")}:
                    raise


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent. PRAGMA user_version is the marker."""
    have = conn.execute("PRAGMA user_version").fetchone()[0]
    if have == 0:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
    elif have > SCHEMA_VERSION:
        sys.exit(f"SCHED-CONFIG database schema v{have} is newer than this script "
                 f"(v{SCHEMA_VERSION}): {DB_PATH}")
    _ensure_columns(conn)


# ---------------------------------------------------------------------------
# Origins: a transport plus a kind. ONE parser (parse_origin), one validator
# (check_origin), ONE writer (encode_origin) and ONE reader (decode_origin), so the two
# stored formats meet in exactly two functions and nowhere else.
# ---------------------------------------------------------------------------

# The fleet tree this file belongs to, through any personal skill link. ⚠️ realpath,
# never abspath: invoked through a link, abspath is the link path under the agent's
# config directory, and three parents up from there is not the fleet tree.
FLEET_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))))), "lib")

ADDRESS_KINDS = ("channel", "dm")   # what an address names; a thread makes it `thread`
LEGACY_REFUSAL = ("REFUSED: this scheduler database predates transport-neutral origins "
                  "and stores Slack origins only; a {transport} origin needs a database "
                  "created by this version.")
ORIGIN_USAGE = ("--origin is 'session', '<transport>:<kind>:<conversation>[:<thread>]' "
                "with kind channel or dm, or one of the forms 'slack:<channel id>' and "
                "'dm:<id>'")

_registry_cache = None


def _refuse(msg: str):
    """A refusal that changed nothing: one line on stderr, exit 2."""
    print(msg, file=sys.stderr, flush=True)
    sys.exit(2)


def _by_name(descriptors) -> dict:
    if isinstance(descriptors, dict):
        return dict(descriptors)
    return {d["name"]: d for d in descriptors}


def transport_registry() -> tuple:
    """(every transport, the working ones), each {name: descriptor}, from fleetlib.

    Imported on first use and never at module load: the tick loop never needs it - the
    emit path decodes stored origins without it - so a fleet library that fails to
    import costs `add` and `set-meta` their validation and never costs the daemon its
    clock.
    """
    global _registry_cache
    if _registry_cache is None:
        if FLEET_LIB not in sys.path:
            sys.path.insert(0, FLEET_LIB)
        try:
            from fleetlib import transports
            _registry_cache = (_by_name(transports.all()), _by_name(transports.working()))
        except Exception as e:  # noqa: BLE001 - every failure here is the same finding
            sys.exit(f"SCHED-CONFIG cannot read the fleet's transport registry through "
                     f"fleetlib in {FLEET_LIB} ({type(e).__name__}: {e})")
    return _registry_cache


def default_requester_pattern(working: dict) -> str:
    """The alternation of every working transport's `ids.user`, in transport-name order.
    With no working transport it matches nothing, so nothing is refused as id-shaped."""
    pats = [working[name]["ids"]["user"] for name in sorted(working)]
    return "|".join(f"(?:{p})" for p in pats) if pats else r"(?!)"


def requester_id_pattern() -> str:
    """requester.id_pattern when the config sets one, else the working transports'."""
    if REQUESTER_ID_PATTERN is not None:
        return REQUESTER_ID_PATTERN
    return default_requester_pattern(transport_registry()[1])


def parse_origin(spec: str, thread: str | None = None) -> tuple:
    """--origin and --thread to (transport, kind, conversation, thread). Grammar only.

      session                                      -> (None, 'session', '-', None)
      <transport>:<kind>:<conversation>            kind is channel or dm
      <transport>:<kind>:<conversation>:<thread>   the stored kind becomes `thread`
      slack:<id>   dm:<id>                         = slack:channel:<id>, slack:dm:<id>

    One colon is the legacy form, two or three the transport grammar. The legacy forms
    are accepted forever: charters, the knowledge base and skill prose teach them.

    `--thread` keeps the meaning it always had: it turns a channel origin into a thread
    origin and leaves a dm a dm, storing the thread id either way. The conversation and
    the thread are always stored together - a thread id paired with the wrong
    conversation posts somewhere else silently rather than erroring.
    """
    if spec == "session":
        if thread:
            _refuse("REFUSED: --thread has no meaning for a session origin")
        return None, "session", "-", None
    parts = spec.split(":")
    inline = None
    if len(parts) == 2:
        legacy = {"slack": ("slack", "channel"), "dm": ("slack", "dm")}
        if parts[0] not in legacy:
            _refuse(f"REFUSED: --origin {spec!r} is not an origin. {ORIGIN_USAGE}.")
        (transport, kind), conversation = legacy[parts[0]], parts[1]
    elif len(parts) in (3, 4):
        transport, kind, conversation = parts[:3]
        inline = parts[3] if len(parts) == 4 else None
        if not transport or kind not in ADDRESS_KINDS or inline == "":
            _refuse(f"REFUSED: --origin {spec!r} is not an origin. {ORIGIN_USAGE}.")
    else:
        _refuse(f"REFUSED: --origin {spec!r} is not an origin. {ORIGIN_USAGE}.")
    if not conversation:
        _refuse(f"REFUSED: --origin {spec!r} names no conversation. {ORIGIN_USAGE}.")
    if inline and thread and inline != thread:
        _refuse(f"REFUSED: --origin names thread {inline} and --thread names {thread}; "
                f"give the thread once")
    if inline:
        return transport, "thread", conversation, inline
    if thread:
        return transport, ("thread" if kind == "channel" else kind), conversation, thread
    return transport, kind, conversation, None


def check_origin(transport, conversation: str, thread) -> None:
    """The transport is a WORKING one in this fleet and the ids have its shapes.

    A placeholder transport is refused here by name: it has a descriptor and no
    implementation, so a task on it would fire into a reply nobody can send.
    """
    if transport is None:
        return
    every, working = transport_registry()
    names = ", ".join(sorted(working)) or "none"
    if transport not in working:
        if transport in every:
            _refuse(f"REFUSED: {transport} is a placeholder transport, not implemented in "
                    f"this version; origins are accepted on working transports only "
                    f"({names}).")
        _refuse(f"REFUSED: this fleet has no transport named {transport!r} (working: "
                f"{names}).")
    ids = working[transport]["ids"]
    if not re.fullmatch(ids["conversation"], conversation):
        _refuse(f"REFUSED: {conversation!r} is not a {transport} conversation id "
                f"({ids['conversation']}).")
    if thread is not None and not re.fullmatch(ids["message"], thread):
        _refuse(f"REFUSED: {thread!r} is not a {transport} message id ({ids['message']}).")


def is_legacy(conn: sqlite3.Connection) -> bool:
    """A tasks table without `origin_transport`: created before transport-neutral
    origins, so it stores the Slack-only vocabulary. A database with no tasks table
    yet is not legacy - migrate() gives it SCHEMA."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    return bool(cols) and "origin_transport" not in cols


def db_is_legacy(path: str) -> bool:
    """is_legacy() for the database at `path`, opened READ-ONLY and never created:
    `add` asks before its dry run, and a refused add leaves no database behind."""
    if not os.path.exists(path):
        return False
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_SECS)
    try:
        return is_legacy(conn)
    finally:
        conn.close()


def encode_origin(legacy: bool, transport, kind: str) -> tuple:
    """(origin_kind, origin_transport) to store. A legacy database stores a Slack origin
    as slack_<kind> and refuses every other transport, exit 2."""
    if kind == "session":
        return "session", None
    if not legacy:
        return kind, transport
    if transport != "slack":
        _refuse(LEGACY_REFUSAL.format(transport=transport))
    return "slack_" + kind, None


def decode_origin(row) -> tuple:
    """(transport, kind) of a stored row, from either format. The one reader."""
    kind = row["origin_kind"]
    if kind == "session":
        return None, "session"
    if kind.startswith("slack_"):
        return "slack", kind[len("slack_"):]
    return _opt(row, "origin_transport"), kind


# ---------------------------------------------------------------------------
# Predicate engine - everything below is PURE and takes its clock as an argument.
# That single rule is what makes the whole loop testable without sleeping.
# ---------------------------------------------------------------------------


class PredicateError(Exception):
    """A deterministic fault: bad syntax, a rejected construct, a bad return shape.

    Deterministic means retrying is pointless, so these fail a task on the FIRST
    strike - three identical log lines a second apart help nobody.
    """
    immediate = True


class PredicateTimeout(Exception):
    """Wall-clock budget exceeded. Could be transient (a pathological date walk on one
    particular day), so this takes a strike rather than failing outright."""
    immediate = False


_DENY_NODES = (
    ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef,
    ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
    ast.Yield, ast.YieldFrom,
    ast.Try, ast.TryStar, ast.ExceptHandler,
)
_DENY_CALLS = {
    "eval", "exec", "compile", "open", "input", "print", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "dir", "type", "id", "help", "memoryview", "breakpoint", "exit", "quit",
}


def validate_predicate(src: str) -> None:
    """Reject a snippet that could escape, hang unkillably, or fail to define the entry
    point. Runs at `add` (so a bad snippet never reaches the DB) and again at cache fill
    (so a hand-edited row is caught too) - never in the hot path, because the compile
    cache makes it once per snippet, not once per tick.
    """
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as e:
        raise PredicateError(f"syntax error line {e.lineno}: {e.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, _DENY_NODES):
            name = type(node).__name__
            if name in ("Try", "TryStar", "ExceptHandler"):
                # Not fussiness - the only in-process fix for a real hole. A bare
                # handler swallows the timer's exception and loops forever, taking the
                # daemon's main loop with it. No timer-based guard survives it, and a
                # predicate has nothing legitimate to catch: state.get(k, default)
                # covers the only realistic need.
                raise PredicateError(
                    "try/except is not allowed in a predicate - it would swallow the "
                    "evaluation timeout and hang the scheduler")
            raise PredicateError(f"{name} is not allowed in a predicate")
        # The underscore rule is the one that matters: every escape from a
        # builtins-free namespace goes through a dunder -
        # ().__class__.__base__.__subclasses__() reaches every loaded class from a bare
        # tuple literal with no builtins at all. Banning leading underscores on names
        # and attributes closes that path, and __import__ with it.
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise PredicateError(f"attribute '{node.attr}' is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise PredicateError(f"name '{node.id}' is not allowed")
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            raise PredicateError("underscore-prefixed definitions are not allowed")
        if isinstance(node, ast.arg) and node.arg.startswith("_"):
            raise PredicateError("underscore-prefixed arguments are not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _DENY_CALLS:
            raise PredicateError(f"call to '{node.func.id}' is not allowed")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "should_fire"
               for n in tree.body):
        raise PredicateError("predicate must define `def should_fire(now, state):` "
                             "at the top level")


def sha_of(src: str) -> str:
    return hashlib.sha256(src.encode()).hexdigest()


# --- helpers exposed to predicates -----------------------------------------


def _tzinfo(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise PredicateError(f"unknown timezone '{tz_name}': {e}") from None


def _at_time(dt, hour, minute=0, second=0):
    """That day's local wall-clock time, same tz as dt."""
    return dt.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _nth_weekday(year, month, weekday, n):
    """Date of the nth (1-based) `weekday` in that month, or None if there isn't one."""
    first = datetime.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (n - 1) * 7
    if day > calendar.monthrange(year, month)[1]:
        return None
    return datetime.date(year, month, day)


def due_slots(from_ts, to_ts, hours, tz, skip=None, minute=0,
              max_slots=None, max_lookback_days=None):
    """Every local wall-clock due instant in (from_ts, to_ts], oldest first.

    `hours` is a sequence of local hours; `skip(date) -> bool` drops whole days.

    DST-correct because each slot is built as a LOCAL wall-clock time and only then
    converted to an epoch - a naive `last + 86400` walks off by an hour twice a year,
    and the symptom is a 09:00 report arriving at 08:00, which reads as flakiness
    rather than as a bug.

    Bounded two ways: never looks back further than max_lookback_days from to_ts, and
    returns at most the newest max_slots. A task resumed after a year of downtime
    therefore coalesces to one fire with a large-but-finite missed count instead of
    walking 8760 hours inside the evaluation timeout.
    """
    max_slots = MAX_DUE_SLOTS if max_slots is None else max_slots
    max_lookback_days = MAX_LOOKBACK_DAYS if max_lookback_days is None else max_lookback_days
    if to_ts <= from_ts:
        return []
    floor_ts = to_ts - max_lookback_days * 86400
    start_ts = max(from_ts, floor_ts)
    d0 = datetime.datetime.fromtimestamp(start_ts, tz).date()
    d1 = datetime.datetime.fromtimestamp(to_ts, tz).date()
    hours = sorted(set(hours))
    out = []
    day = d0
    one = datetime.timedelta(days=1)
    while day <= d1:
        if skip is None or not skip(day):
            for h in hours:
                ts = datetime.datetime(day.year, day.month, day.day, h, minute,
                                       tzinfo=tz).timestamp()
                if from_ts < ts <= to_ts:
                    out.append(ts)
        day += one
    out.sort()
    return out[-max_slots:] if len(out) > max_slots else out


def interval_slots(last_ts, to_ts, interval, max_slots=None):
    """Every `interval`-spaced instant strictly after last_ts, up to and including to_ts.

    The interval analogue of due_slots(): len() is how many due times passed, so the
    same coalescing shape works for "every 90 seconds" as for "daily at 09:00".
    """
    max_slots = MAX_DUE_SLOTS if max_slots is None else max_slots
    if interval <= 0 or to_ts <= last_ts:
        return []
    n = int((to_ts - last_ts) // interval)
    if n <= 0:
        return []
    n = min(n, max_slots)
    return [last_ts + interval * (i + 1) for i in range(n)]


_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "divmod": divmod, "enumerate": enumerate, "filter": filter, "float": float,
    "int": int, "isinstance": isinstance, "len": len, "list": list, "map": map,
    "max": max, "min": min, "range": range, "reversed": reversed, "round": round,
    "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "True": True, "False": False, "None": None,
    # deliberately absent: __import__ open eval exec compile getattr setattr delattr
    # globals locals vars dir type input print id help
}


_BOOT_TIME_CACHE: list = []
# Where the boot time is read: Linux's /proc/stat btime, else (macOS, which has no
# /proc) the kernel's kern.boottime through sysctl(8). Module constants so the test can
# point either at a fixture; nothing else changes them.
PROC_STAT = "/proc/stat"
SYSCTL = "/usr/sbin/sysctl"


def parse_kern_boottime(text: str) -> float:
    """Epoch seconds from `sysctl -n kern.boottime` output, `{ sec = 1790640234, usec =
    174452 } Fri Oct  3 10:03:54 2026`, or 0.0. Anchored on the opening brace: the
    `usec = ` field also contains `sec = `, and a match on it reads microseconds as the
    boot time (an uptime of decades, so every guard silently passes)."""
    m = re.search(r"\{\s*sec\s*=\s*(\d+)", text or "")
    return float(m.group(1)) if m else 0.0


def host_boot_time() -> float:
    """Epoch seconds at which this host booted: /proc/stat btime on Linux, sysctl
    kern.boottime where there is no /proc/stat (macOS).

    ⚠️ Read ONCE and cached for the process lifetime, deliberately. btime is a constant
    for a given boot, and re-reading it per evaluation would put a second live clock in
    the namespace - the exact thing `now` exists to prevent. Cached, it is a constant
    injected at namespace construction, so `should_fire(now, state)` stays a pure
    function of its inputs and the simulator stays faithful.

    Returns 0.0 if neither source answers. 0.0 reads as "booted at the epoch", i.e.
    infinite uptime, which makes every uptime guard a no-op. That is the correct failure
    direction (a guard that cannot evaluate should not suppress work), and it is also
    SILENT: a reader that only knew /proc turned every guard off on macOS with nothing
    to say so. sched.test.py therefore requires a real epoch on the hosts the fleet
    supports, rather than accepting 0.0 as an answer.
    """
    if not _BOOT_TIME_CACHE:
        bt = 0.0
        try:
            with open(PROC_STAT) as fh:
                for line in fh:
                    if line.startswith("btime "):
                        bt = float(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            bt = 0.0
        if not bt and os.path.exists(SYSCTL):
            try:
                bt = parse_kern_boottime(subprocess.run(
                    [SYSCTL, "-n", "kern.boottime"], capture_output=True, text=True,
                    stdin=subprocess.DEVNULL, timeout=10).stdout)
            except (OSError, subprocess.SubprocessError):
                bt = 0.0
        _BOOT_TIME_CACHE.append(bt)
    return _BOOT_TIME_CACHE[0]


def safe_globals(tz_name: str, boot_time: float = None) -> dict:
    """The predicate's entire world. No modules - a module is a namespace an author can
    walk - only classes, functions and constants, with the AST underscore rule as the
    thing that actually closes the attribute path.

    `boot_time` is injected rather than read here so the simulator and the tests can set
    it. It defaults to this host's real boot time for the daemon, and to 0.0 (infinite
    uptime) in `simulate`, so a simulation shows the schedule a long-lived host would
    run rather than one suppressed by a guard.
    """
    tz = _tzinfo(tz_name)
    bt = host_boot_time() if boot_time is None else float(boot_time)
    return {
        "BOOT_TIME": bt,
        # uptime(now) - seconds this host has been up as of `now`. The reason this
        # exists: a task whose ACTION destroys the session that reports it (reboot,
        # agent restart, restarting a unit the session depends on) will, if its slot
        # was missed, fire again on the next boot and destroy the session again. The
        # cycle is not self-limiting, because the run-result that would advance the
        # state is never written. Guard such predicates with:
        #     if uptime(now) < 3600: return {"fire": False, "state": state}
        # SKILL.md section 5 ("BOOT_TIME and uptime(now)") says why, and that the
        # guard must consume the slot rather than defer it.
        "uptime": lambda now: (now - bt) if bt else float("inf"),
        "__builtins__": dict(_SAFE_BUILTINS),
        # time vocabulary
        "datetime": datetime.datetime, "date": datetime.date,
        "time_of_day": datetime.time, "timedelta": datetime.timedelta,
        "timezone": datetime.timezone, "UTC": datetime.timezone.utc,
        "math": math,
        # task context
        "TZ": tz, "TZNAME": tz_name,
        "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
        # helpers
        "local": lambda ts: datetime.datetime.fromtimestamp(ts, tz),
        "epoch": lambda dt: dt.timestamp(),
        "at_time": _at_time,
        "day_start": lambda dt: _at_time(dt, 0),
        "is_leap": calendar.isleap,
        "days_in_month": lambda y, m: calendar.monthrange(y, m)[1],
        "nth_weekday": _nth_weekday,
        "due_slots": due_slots,
        "interval_slots": interval_slots,
    }


_CODE_CACHE: dict[str, types.CodeType] = {}


def load_code(sha: str, src: str) -> types.CodeType:
    code = _CODE_CACHE.get(sha)
    if code is None:
        validate_predicate(src)
        code = compile(src, f"<predicate {sha[:8]}>", "exec")
        if len(_CODE_CACHE) >= CODE_CACHE_MAX:
            _CODE_CACHE.clear()
        _CODE_CACHE[sha] = code
    return code


@contextlib.contextmanager
def eval_guard(seconds: float):
    """Wall-clock bound on one predicate evaluation.

    setitimer, NOT signal.alarm: alarm() takes whole seconds, so the smallest
    enforceable bound would be a full tick spent on one bad task - and "1" really means
    "somewhere between 0 and 1". setitimer is the same SIGALRM mechanism with float
    resolution, still stdlib.

    SIGALRM is main-thread-only, so this asserts rather than becoming a silent no-op.
    Disarming in `finally` is not optional: a timer left armed after a slow-but-
    successful evaluation fires during the NEXT task and fails an innocent one.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("eval_guard requires the main thread")

    def _boom(signum, frame):
        raise PredicateTimeout(f"predicate exceeded {seconds}s")

    prev = signal.signal(signal.SIGALRM, _boom)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)


class EvalResult:
    __slots__ = ("fire", "state", "missed", "done", "note")

    def __init__(self, fire, state, missed=0, done=False, note=""):
        self.fire, self.state, self.missed = fire, state, missed
        self.done, self.note = done, note

    def __repr__(self):
        return (f"EvalResult(fire={self.fire}, missed={self.missed}, "
                f"done={self.done}, state={self.state!r})")


_RESULT_KEYS = {"fire", "state", "missed", "done", "note"}


def normalize_result(raw, prev_state: dict) -> EvalResult:
    """Accept True / (bool, state) / {...}; reject everything else, loudly and at once.

    Every rejection here is a deterministic bug in the snippet, so all of them are
    PredicateError (immediate), not a strike.
    """
    if raw is True or raw is False:
        return EvalResult(raw, prev_state)
    if isinstance(raw, tuple):
        if len(raw) != 2:
            raise PredicateError(f"tuple result must be (fire, state), got {len(raw)} items")
        fire, state = raw
        if not isinstance(fire, bool):
            raise PredicateError(f"first tuple item must be a bool, got {type(fire).__name__}")
        return EvalResult(fire, _check_state(state))
    if isinstance(raw, dict):
        unknown = set(raw) - _RESULT_KEYS
        if unknown:
            raise PredicateError(f"unknown result key {sorted(unknown)[0]!r}")
        if "fire" not in raw:
            raise PredicateError("result dict has no 'fire' key")
        fire = raw["fire"]
        if not isinstance(fire, bool):
            raise PredicateError(f"'fire' must be a bool, got {type(fire).__name__}")
        state = _check_state(raw["state"]) if "state" in raw else prev_state
        missed = raw.get("missed", 0)
        if not isinstance(missed, int) or isinstance(missed, bool) or missed < 0:
            raise PredicateError(f"'missed' must be an int >= 0, got {missed!r}")
        done = raw.get("done", False)
        if not isinstance(done, bool):
            raise PredicateError(f"'done' must be a bool, got {type(done).__name__}")
        note = raw.get("note", "")
        if not isinstance(note, str):
            raise PredicateError(f"'note' must be a str, got {type(note).__name__}")
        return EvalResult(fire, state, missed, done, note)
    raise PredicateError(
        f"should_fire must return a bool, (bool, state) or a dict, got {type(raw).__name__}")


def _json_ok(obj) -> bool:
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _check_state(state) -> dict:
    if not isinstance(state, dict):
        raise PredicateError(f"state must be a dict, got {type(state).__name__}")
    try:
        rt = json.loads(json.dumps(state))
    except (TypeError, ValueError) as e:
        bad = next((k for k in state if not _json_ok({k: state[k]})), None)
        raise PredicateError(
            f"state is not JSON-serializable"
            + (f" (key {bad!r})" if bad else "") + f": {e}") from None
    if rt != state:
        # Catches {"seen": {1, 2}} - a set survives json.dumps as a list and comes back
        # as a list next tick, silently changing what the predicate does on day two.
        bad = [k for k in state if json.loads(json.dumps({k: state[k]}))[k] != state[k]]
        raise PredicateError(
            f"state does not round-trip through JSON unchanged (key {bad[0]!r})"
            if bad else "state does not round-trip through JSON unchanged")
    return state


def evaluate(row, now: float, timeout: float = None,
             boot_time: float = None) -> EvalResult:
    """Run one predicate. Pure with respect to the DB - takes a mapping, returns a
    result, touches nothing.

    `boot_time` defaults to this host's real boot time; `simulate` passes 0.0 so a
    simulation is not suppressed by an uptime guard."""
    timeout = EVAL_TIMEOUT_SECS if timeout is None else timeout
    code = load_code(row["predicate_sha"], row["predicate_src"])
    g = safe_globals(row["tz"], boot_time)
    state = json.loads(row["state_json"] or "{}")
    with eval_guard(timeout):
        exec(code, g)
        fn = g.get("should_fire")
        if not callable(fn):
            raise PredicateError("should_fire is not callable")
        # deepcopy: a snippet that mutates its argument cannot corrupt the state we
        # still hold for the "did it change?" comparison.
        raw = fn(now, copy.deepcopy(state))
    return normalize_result(raw, state)


# ---------------------------------------------------------------------------
# Simulator - the same code path the daemon runs, with a fake clock.
# ---------------------------------------------------------------------------


def simulate(src, tz, start, end, step=60.0, state=None, outages=(),
             max_fires=None, min_interval=0.0, timeout=None, boot_time=0.0):
    """Fast-forward a simulated clock and return every fire the predicate produces.

    `outages` are (from_ts, to_ts) windows in which the predicate is simply NOT CALLED
    while the clock keeps advancing - which is exactly what a dead daemon looks like,
    and is therefore how coalescing gets validated before anything is armed.

    Pure: no DB, no wall clock, no I/O. Deterministic, because a predicate has no clock
    but `now` and no randomness available at all.
    """
    sha = sha_of(src)
    validate_predicate(src)
    row = {"predicate_sha": sha, "predicate_src": src, "tz": tz,
           "state_json": json.dumps(state or {})}
    fires, err, slowest, evals, deferred = [], None, 0.0, 0, 0
    last_fire = None
    t = float(start)
    while t <= end:
        if any(a <= t <= b for a, b in outages):
            t += step
            continue
        t0 = time.monotonic()
        try:
            res = evaluate(row, t, timeout=timeout, boot_time=boot_time)
        except (PredicateError, PredicateTimeout) as e:
            err = f"{type(e).__name__}: {e}"
            break
        except Exception as e:                       # noqa: BLE001 - report, don't crash
            err = f"{type(e).__name__}: {e}"
            break
        slowest = max(slowest, time.monotonic() - t0)
        evals += 1
        if res.fire and min_interval and last_fire is not None \
                and t - last_fire < min_interval:
            # Deferred by the emit floor exactly as the daemon defers it: the state
            # write is skipped so the decision is recomputed next step.
            deferred += 1
            t += step
            continue
        row["state_json"] = json.dumps(res.state)
        if res.fire:
            fires.append({"at": t, "missed": res.missed, "note": res.note,
                          "state": res.state, "done": res.done})
            last_fire = t
            if res.done or (max_fires and len(fires) >= max_fires):
                break
        t += step
    span_days = max((end - start) / 86400.0, 1e-9)
    return {
        "fires": fires,
        "error": err,
        "summary": {
            "evals": evals, "days": span_days, "deferred": deferred,
            "per_day": len(fires) / span_days,
            "slowest_eval_ms": slowest * 1000.0,
            "done": bool(fires and fires[-1]["done"]),
            "final_state": json.loads(row["state_json"]),
        },
    }


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def _opt(row, key):
    """Read a column that a pre-migration row - or a hand-built dict in a test - may not
    carry at all. sqlite3.Row raises IndexError for an absent key and a dict raises
    KeyError; neither is a reason to lose a wake-up line."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _fit(text: str, budget: int, pointer: str) -> str:
    """Trim to budget, degrading into a pointer to the full text rather than into a
    sentence that stops mid-clause and reads as complete.

    ⚠️ IT NEVER RETURNS MORE THAN `budget`, including when the budget cannot hold the
    pointer - in which case it returns nothing at all. The tempting version appends the
    pointer regardless, which quietly makes every payload segment cost at least
    len(pointer) no matter what it was given, and two segments then push the line past
    emit.max_line_chars on exactly the tasks with the least room. Dropping the segment
    loses nothing a reader can use: the task id is in the prefix, which is never
    truncated, so `sched.py show <id>` is derivable from what remains.
    """
    if len(text) <= budget:
        return text
    if budget < len(pointer):
        return ""
    return text[:budget - len(pointer)].rstrip() + pointer


def format_emit(row, run_id, missed=0, replay=False) -> str:
    """One line, built purely so the tests can pin it byte-for-byte without a DB.

    Nothing structural is ever truncated. A truncated task id or channel id is worse
    than useless - it is actively wrong - so an over-long payload degrades into a
    pointer rather than into a lie.

    ⚠️ THE REASON IS PLACED BEFORE THE INSTRUCTION AND THAT ORDER IS LOAD-BEARING. The
    payload is what the line budget cuts, and it cuts from the end - so with the
    instruction first, any task whose instruction is long enough to truncate loses its
    reason entirely, silently, on exactly the wake-up where the agent is least able to
    ask why the task exists. Reason first means a long instruction is what gets cut, and
    the instruction's truncation already carries a pointer to its own full text. The
    reason gets its own smaller budget (emit.reason_chars) so it cannot starve the
    instruction in return.
    """
    # The label is the one UNBOUNDED thing in the prefix, and the prefix is what the
    # payload's budget is subtracted from - an over-long one starves the instruction
    # and the reason both. It is also the one prefix element that is cosmetic: ids are
    # never truncated because a truncated id is actively wrong, a truncated label is
    # merely shorter. `show` still prints it in full.
    origin = origin_display(row, label_chars=TITLE_CHARS)
    parts = [
        "SCHED due",
        f"[{row['id']}]",
        f"run={run_id}",
        f'"{collapse(row["title"])[:TITLE_CHARS]}"',
        f"origin={origin}",
    ]
    # Which transport the answer goes out on: the reader loads that transport's skill to
    # reply. Omitted for a session origin, which has none.
    transport = decode_origin(row)[0]
    if transport:
        parts.append(f"via={transport}")
    if row["origin_thread"]:
        parts.append(f"thread={row['origin_thread']}")
    # Quoted like the title, and for a mechanical reason rather than symmetry: the
    # prefix is documented as a space-separated field list, and this value now holds
    # human text - `claude cli terminal` is in the vocabulary, so a space in it is
    # certain rather than hypothetical. Unquoted, a reader tokenising the line gets
    # `by=claude` and two stray words where `missed=` should be. Capped for the same
    # reason the title is: it is prefix, and prefix is what the payload budget is
    # subtracted from.
    parts.append(f'by="{collapse(row["requester_uid"])[:REQUESTER_CHARS]}"')
    parts.append(f"missed={missed}")
    if replay:
        parts.append("replay=1")
    prefix = " ".join(parts)
    pointer = f" ... (full text: sched.py show {row['id']})"
    budget = MAX_LINE_CHARS - len(prefix) - 3
    payload = []
    reason = collapse(_opt(row, "reason") or "")
    # ⚠️ THE GUARD IS NOT `if reason`. Once an unusually long prefix has eaten the
    # budget, _fit returns a bare pointer, and `why:  ... (full text: ...)` is a why
    # carrying no why - which has ALSO spent ~48 characters of the instruction's
    # budget to say nothing. Same output for emit.reason_chars: 0, which is how an
    # operator would try to turn the reason off. Below the floor the reason is
    # dropped whole and the instruction gets the room: an absent segment is honest,
    # a segment that renders as a stub is not. The +8 leaves space for `why: ` and
    # for the ` - ` that follows it, both of which are outside the budget arithmetic.
    reason_budget = min(REASON_CHARS, budget - 8)
    if reason and reason_budget > len(pointer):
        head = "why: " + _fit(reason, reason_budget, pointer)
        payload.append(head)
        budget -= len(head) + 3
    payload.append(_fit(collapse(row["instruction"]), budget, pointer))
    payload = [seg for seg in payload if seg]
    return f"{prefix} - " + " - ".join(payload) if payload else prefix


def origin_display(row, label_chars: int | None = None) -> str:
    kind, oid = row["origin_kind"], row["origin_id"]
    label = row["origin_label"]
    if kind == "session":
        return "session"
    if label:
        lbl = collapse(label)
        return f"{oid}({lbl[:label_chars] if label_chars else lbl})"
    return oid


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def _now_i(now: float) -> int:
    return int(now)


def _finish(conn, row, reason: str, now: float) -> bool:
    return conn.execute(
        "UPDATE tasks SET status='done', finished_at=?, finished_reason=?, "
        "updated_at=?, rev=rev+1 WHERE id=? AND rev=? AND status='active'",
        (_now_i(now), reason, _now_i(now), row["id"], row["rev"]),
    ).rowcount > 0


def _record_eval_error(conn, row, e: BaseException, now: float) -> None:
    """State is deliberately NOT written on a failing evaluation, so a task fixed with
    `resume --reset-errors` restarts from its last good state rather than from {}."""
    immediate = getattr(e, "immediate", False)
    msg = f"{type(e).__name__}: {e}"[:500]
    new_count = MAX_ERRORS if immediate else row["error_count"] + 1
    status = "failed" if new_count >= MAX_ERRORS else "active"
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE tasks SET error_count=?, last_error=?, last_eval_at=?, updated_at=?, "
            "status=?, finished_at=?, finished_reason=?, rev=rev+1 "
            "WHERE id=? AND rev=? AND status='active'",
            (new_count, msg, _now_i(now), _now_i(now), status,
             _now_i(now) if status == "failed" else None,
             "predicate error" if status == "failed" else None,
             row["id"], row["rev"]),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    log_error(f"eval {row['id']}", e)


def _trim_runs(conn, task_id: str) -> None:
    conn.execute(
        "DELETE FROM runs WHERE task_id=? AND run_id NOT IN "
        "(SELECT run_id FROM runs WHERE task_id=? ORDER BY fired_at DESC LIMIT ?)",
        (task_id, task_id, RUNS_PER_TASK),
    )


def run_tick(conn, now: float, warn: dict | None = None) -> list[str]:
    """One evaluation pass. Returns the lines to print - the caller prints them, so the
    ordering rule (COMMIT strictly before print) is visible in one place.

    Read on a WAL snapshot holding no lock → evaluate holding no lock (untrusted code
    must never block the CLI) → one short BEGIN IMMEDIATE per fire.
    """
    warn = {} if warn is None else warn
    # Oldest-waiting first. With max_fires_per_tick capping emissions, a stable order
    # would let the same early rows win every tick and starve everything below them -
    # so the tie-break is "who has gone longest without firing".
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='active' AND (not_before IS NULL OR not_before<=?) "
        "ORDER BY COALESCE(last_fire_at, 0) ASC, created_at ASC",
        (_now_i(now),),
    ).fetchall()
    if len(rows) > MAX_ACTIVE_TASKS:
        log_info(f"{len(rows)} active tasks exceeds loop.max_active_tasks="
                 f"{MAX_ACTIVE_TASKS}; evaluation is still cheap but emit volume may not be",
                 warn, "too_many")

    lines, fired = [], 0
    for row in rows:
        # Hard expiry is checked BEFORE the predicate, so an expired task needs no
        # cooperation from a snippet that may itself be the reason it is expiring.
        if row["not_after"] is not None and now > row["not_after"]:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _finish(conn, row, "not_after reached", now)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            continue

        try:
            res = evaluate(row, now)
        except Exception as e:                        # noqa: BLE001 - one bad task
            _record_eval_error(conn, row, e, now)     # must never end the loop
            continue

        old_state = json.loads(row["state_json"] or "{}")
        state_changed = res.state != old_state

        if not res.fire:
            if state_changed:
                _write_state(conn, row, res.state, now)
            continue

        floor = row["min_interval"] if row["min_interval"] is not None else MIN_INTERVAL_SECS
        if floor and row["last_fire_at"] and now - row["last_fire_at"] < floor:
            # The runaway guard. Enforced regardless of what the predicate returned,
            # because a snippet stuck at fire=True would otherwise inject a wake-up
            # every tick and make the session unusable.
            #
            # DEFERRED, not dropped: the state write is skipped, so the predicate
            # recomputes the identical decision and fires as soon as the floor passes.
            # Writing the state here would advance the predicate past a due time that
            # was never announced - a silently lost occurrence, which is the failure
            # this whole system is built to avoid.
            log_info(f"{row['id']} came due within {floor:.0f}s of its last fire; "
                     f"deferred by emit.min_interval_secs (raise the task's "
                     f"--min-interval if this cadence is intended)", warn, f"floor:{row['id']}")
            continue

        if fired >= MAX_FIRES_PER_TICK:
            # Deferred, not dropped: nothing is written, so the next tick recomputes the
            # identical decision. Purity is what makes that safe.
            continue

        line = _commit_fire(conn, row, res, now)
        if line:
            lines.append(line)
            fired += 1
    return lines


def _write_state(conn, row, state: dict, now: float) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        n = conn.execute(
            "UPDATE tasks SET state_json=?, last_eval_at=?, updated_at=?, rev=rev+1 "
            "WHERE id=? AND rev=? AND status='active'",
            (json.dumps(state), _now_i(now), _now_i(now), row["id"], row["rev"]),
        ).rowcount
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return n > 0


def _commit_fire(conn, row, res: EvalResult, now: float) -> str | None:
    """Write the fire, then hand the line back to be printed.

    `WHERE id=? AND rev=?` is the cancel race: a `cancel` landing between evaluation and
    commit means no state write and NO EMIT, and the task is simply re-read next tick.
    Losing one second is always safe because predicates are pure.
    """
    fire_count = row["fire_count"] + 1
    done = res.done or (row["max_fires"] is not None and fire_count >= row["max_fires"])
    reason = ("predicate" if res.done else "max_fires") if done else None
    conn.execute("BEGIN IMMEDIATE")
    try:
        n = conn.execute(
            "UPDATE tasks SET state_json=?, last_eval_at=?, last_fire_at=?, "
            "fire_count=?, error_count=0, last_error=NULL, status=?, finished_at=?, "
            "finished_reason=?, updated_at=?, rev=rev+1 "
            "WHERE id=? AND rev=? AND status='active'",
            (json.dumps(res.state), _now_i(now), _now_i(now), fire_count,
             "done" if done else "active", _now_i(now) if done else None, reason,
             _now_i(now), row["id"], row["rev"]),
        ).rowcount
        if n == 0:
            conn.execute("ROLLBACK")
            return None
        cur = conn.execute(
            "INSERT OR IGNORE INTO runs(task_id, fired_at, missed, emitted_line) "
            "VALUES (?,?,?,'')", (row["id"], _now_i(now), res.missed))
        if cur.rowcount == 0:
            # Same (task, fired_at) already recorded - a daemon restarted mid-commit.
            # A no-op beats a duplicate wake-up.
            conn.execute("ROLLBACK")
            return None
        run_id = cur.lastrowid
        line = format_emit(row, run_id, res.missed)
        conn.execute("UPDATE runs SET emitted_line=? WHERE run_id=?", (line, run_id))
        _trim_runs(conn, row["id"])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return line


def replay_lost_wakeups(conn, now: float) -> list[str]:
    """A wake-up line injected while the session was restarting is gone forever - there
    is no per-channel cursor to re-read it from. The pending-run index IS that cursor.

    Runs younger than replay_grace_secs are left alone: the daemon may have restarted
    seconds after emitting, and the line is probably still in the session.
    """
    rows = conn.execute(
        "SELECT r.run_id, r.task_id, r.missed, r.replays, t.* FROM runs r "
        "JOIN tasks t ON t.id = r.task_id "
        "WHERE r.status='pending' AND r.started_at IS NULL AND r.fired_at < ? "
        "AND r.replays < ? ORDER BY r.fired_at DESC LIMIT ?",
        (_now_i(now - REPLAY_GRACE_SECS), MAX_REPLAYS_PER_RUN, REPLAY_MAX),
    ).fetchall()
    lines = []
    for r in rows:
        conn.execute("UPDATE runs SET replays=replays+1 WHERE run_id=?", (r["run_id"],))
        lines.append(format_emit(r, r["run_id"], r["missed"], replay=True))
    conn.execute(
        "UPDATE runs SET status='lost' WHERE status='pending' AND started_at IS NULL "
        "AND replays >= ?", (MAX_REPLAYS_PER_RUN,))
    return lines


def auto_archive(conn, now: float) -> int:
    if AUTO_ARCHIVE_DAYS <= 0:
        return 0
    cutoff = _now_i(now) - AUTO_ARCHIVE_DAYS * 86400
    return conn.execute(
        "UPDATE tasks SET status='archived', updated_at=?, rev=rev+1 "
        "WHERE status IN ('done','cancelled','failed') AND finished_at IS NOT NULL "
        "AND finished_at < ?", (_now_i(now), cutoff)).rowcount


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


def run_daemon(once: bool = False) -> None:
    if not once:
        _lock = acquire_singleton_lock()  # noqa: F841 - held for process lifetime
    conn = connect()
    migrate(conn)
    now = time.time()
    for line in replay_lost_wakeups(conn, now):
        print(line, flush=True)
    active = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='active'").fetchone()[0]
    log_info(f"scheduler up - db={DB_PATH} active={active} tick={TICK_SECS}s "
             f"eval_timeout={EVAL_TIMEOUT_SECS}s tz={DEFAULT_TZ}")

    warn: dict = {}
    next_tick = time.monotonic()
    db_errors = 0
    last_archive = 0.0
    while True:
        try:
            now = time.time()
            for line in run_tick(conn, now, warn):
                print(line, flush=True)
            if now - last_archive > 86400:
                n = auto_archive(conn, now)
                last_archive = now
                if n:
                    log_info(f"archived {n} terminal task(s) older than {AUTO_ARCHIVE_DAYS}d")
            db_errors = 0
        except sqlite3.OperationalError as e:      # locked/busy - skip a tick, never die
            log_error("tick", e)
        except sqlite3.DatabaseError as e:         # corrupt / not a database
            db_errors += 1
            log_error("db", e)
            if db_errors >= DB_FATAL_STRIKES:
                emit_alert(f"scheduler DB unusable after {db_errors} ticks: {e} - NO "
                           f"scheduled task will fire until this is fixed", time.time())
                sys.exit(f"SCHED-CONFIG database unusable: {DB_PATH} - {e}")
        except Exception as e:                     # noqa: BLE001 - a bug here must not
            log_error("loop", e)                   # stop the fleet's clock

        if once:
            return
        next_tick += TICK_SECS
        lag = time.monotonic() - next_tick
        if lag > RESYNC_LAG_SECS:
            # Resync, do NOT burst. Predicates are edge-triggered on their own state, so
            # one evaluation at the new time is exactly correct; replaying the missed
            # ticks would just call every predicate N times with nearly the same `now`.
            log_info(f"tick clock resynced after {lag:.0f}s lag")
            next_tick = time.monotonic()
            continue
        if lag < 0:
            time.sleep(-lag)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def new_task_id() -> str:
    return ("tsk_" + time.strftime("%Y%m%dT%H%MZ", time.gmtime())
            + "_" + secrets.token_hex(3))


def resolve_id(conn, prefix: str) -> str:
    rows = conn.execute("SELECT id FROM tasks WHERE id = ? OR id LIKE ?",
                        (prefix, f"%{prefix}%")).fetchall()
    ids = sorted({r["id"] for r in rows})
    if not ids:
        sys.exit(f"no task matching {prefix!r}")
    if len(ids) > 1:
        sys.exit(f"{prefix!r} is ambiguous: {', '.join(ids)}")
    return ids[0]


_REQUESTER_HELP = (
    "the requester's human-readable identity: the display name of the person who asked "
    "(a chat user id is resolved to it), the value naming the interface a human typed it "
    "into when there is no account behind the request, or this agent's own persona name "
    "when the task originates from a standing rule rather than from a person"
)

_REASON_HELP = (
    "why this task exists: why is it here at all, why was it added, and what problem "
    "does it solve - written for a reader who was not in the conversation"
)


def _requester_directory() -> dict:
    """The id → display-name map, or {} when this install configures none.

    Read on demand rather than at import: it is a foreign file (a chat integration's
    config), so a deployment that has none, or whose copy is momentarily unreadable,
    must still be able to run the daemon and the CLI. A directory that cannot be read
    resolves nothing, and resolve_requester() then REFUSES an id-shaped value instead
    of storing it - loud, and at the one moment a human is present to fix it.
    """
    if not REQUESTER_DIRECTORY_FILE or not REQUESTER_DIRECTORY_KEY:
        return {}
    try:
        with open(os.path.expanduser(REQUESTER_DIRECTORY_FILE)) as f:
            node = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    for part in REQUESTER_DIRECTORY_KEY.split("."):
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    # _strip_comments for the same reason it exists here at all: JSON has no comment
    # syntax, so a roster documents itself with leading-underscore keys, and without
    # this `--requester _comment` resolves to the comment text.
    return _strip_comments(node) if isinstance(node, dict) else {}


def _looks_like_id(value: str) -> bool:
    """⚠️ fullmatch, not match. `id_pattern` is caller-supplied and its own comment
    calls it "what an unresolved id LOOKS like", which invites an UNANCHORED pattern -
    and under `match` an unanchored pattern silently refuses any NAME whose prefix
    happens to look id-shaped. fullmatch makes the key mean what it says."""
    try:
        return re.fullmatch(requester_id_pattern(), value) is not None
    except re.error as e:
        # The file's convention for a config value that cannot be used: name the key
        # and exit, never a traceback.
        sys.exit(f"SCHED-CONFIG {CONFIG_FILE}: requester.id_pattern is not a valid "
                 f"regular expression - {e}")


def resolve_requester(value: str) -> str:
    """Return the human-readable requester to store.

    A value already in human form is stored verbatim. A value that is a key in the
    requester directory is replaced by the name it maps to.

    ⚠️ AN ID-SHAPED VALUE THE DIRECTORY CANNOT RESOLVE IS REFUSED, and that refusal is
    the whole point of this function. Storing the id instead would satisfy every schema
    constraint and every test, and the failure would surface months later as a `by=`
    field and a `list` row naming somebody nobody can identify - on a task whose
    requester is the only remaining evidence of whether it should still be running.
    An unreadable identity is not a smaller version of a readable one; it is the exact
    failure the field exists to prevent. Do not soften this into a warning.
    """
    value = collapse(value)
    directory = _requester_directory()
    if value in directory:
        resolved = directory[value]
        # ⚠️ THE ROSTER IS A FOREIGN FILE AND ITS VALUES ARE NOT OURS TO TRUST. A
        # non-string entry (a Slack user OBJECT is the natural shape for one) would
        # otherwise be stringified into `by={'name': 'Ada'}`, and a value carrying a
        # NEWLINE would make format_emit return TWO lines - breaking the one hard
        # output contract this system has, since the second line does not start with
        # the sentinel and is persisted into runs.emitted_line and replayed later.
        if not isinstance(resolved, str) or not collapse(resolved):
            sys.exit(
                f"REFUSED: the requester directory resolves {value!r} to something "
                f"that is not a usable name ({type(resolved).__name__}). A task row "
                f"needs a plain string. Fix the entry in the directory, or pass the "
                f"display name directly."
            )
        return collapse(resolved)
    if _looks_like_id(value):
        sys.exit(
            f"REFUSED: --requester {value!r} looks like a user id and this install's "
            f"requester directory does not resolve it. The task row must carry a name a "
            f"human recognises, not an id - a `by=` nobody can read is exactly the "
            f"failure this field exists to prevent. Either add {value} to the directory "
            f"(requester.directory_file / requester.directory_key in "
            f"{CONFIG_FILE}), or pass the display name itself."
        )
    return value


def parse_when(s: str, tz_name: str) -> int:
    """ISO local time, or +N[smhd] relative to now."""
    if s.startswith("+"):
        unit, num = s[-1], s[1:-1]
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
        if not mult:
            sys.exit(f"bad relative time {s!r} - use +30m, +2h, +7d")
        return int(time.time() + float(num) * mult)
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tzinfo(tz_name))
    return int(dt.timestamp())


def fmt_local(ts, tz_name):
    return datetime.datetime.fromtimestamp(ts, _tzinfo(tz_name)).strftime("%a %d %b %Y %H:%M")


REASON_REFUSAL = """REFUSED: --reason is required.

A schedule outlives the conversation that created it, often by months, and the task row
is all the future reader gets. Answer these three, in the reason itself:

  * Why is this task here at all - what would be worse if it were forgotten?
  * Why was it added - what was happening when someone asked for it?
  * What problem does it solve?

Write it for someone who was not in that conversation. "Ada asked for it" answers
none of the three."""


def cmd_add(a) -> None:
    # Checked before the dry run, so a missing reason is not reported after the human
    # has already been shown a schedule that looks accepted.
    if not (a.reason or "").strip():
        sys.exit(REASON_REFUSAL)
    requester = resolve_requester(a.requester)
    # The origin is settled before the dry run too, for the reason the reason is: a
    # refusal shown after a schedule that looked accepted reads as a retraction. The
    # legacy question comes first, so that a database which can only store Slack says
    # so in its own words whatever the transport's status.
    transport, kind, oid, thread = parse_origin(a.origin, a.thread)
    encode_origin(db_is_legacy(DB_PATH), transport, kind)
    check_origin(transport, oid, thread)
    src = a.predicate if a.predicate else open(a.predicate_file).read()
    tz = a.tz or DEFAULT_TZ
    try:
        validate_predicate(src)
    except PredicateError as e:
        sys.exit(f"predicate rejected: {e}")

    start = time.time()
    sim = simulate(src, tz, start, start + a.simulate_days * 86400, step=a.step,
                   state=json.loads(a.state), max_fires=a.max_fires,
                   min_interval=a.min_interval if a.min_interval is not None
                   else MIN_INTERVAL_SECS)
    if sim["error"]:
        sys.exit(f"predicate failed in dry run: {sim['error']}")
    n, per_day = len(sim["fires"]), sim["summary"]["per_day"]
    print(f"dry run: {n} fire(s) over {a.simulate_days}d ({per_day:.2f}/day)")
    for f in sim["fires"][:5]:
        print(f"  {fmt_local(f['at'], tz)}  missed={f['missed']}  {f['note']}")
    if not a.force:
        # The two mistakes an authored snippet actually makes: one silent for weeks,
        # one loud and immediate. This is the only place either is caught before it
        # reaches production.
        if n == 0:
            sys.exit(f"REFUSED: predicate never fires in {a.simulate_days} days. A dead "
                     f"schedule is indistinguishable from a quiet one - nothing will "
                     f"ever tell you. Fix it, or pass --force if the first fire is "
                     f"genuinely further out than the horizon.")
        if per_day > FIRES_PER_DAY_WARN:
            sys.exit(f"REFUSED: {per_day:.1f} fires/day exceeds add.fires_per_day_warn="
                     f"{FIRES_PER_DAY_WARN}. Every fire is a wake-up line in the agent's "
                     f"session. Pass --force if that is really intended.")

    now = int(time.time())
    tid = new_task_id()
    conn = connect()
    migrate(conn)
    # Re-asked on the open connection, which is the authority: encode_origin is the one
    # writer of either format, and the column list follows the table actually there.
    legacy = is_legacy(conn)
    origin_kind, origin_transport = encode_origin(legacy, transport, kind)
    cols = {"id": tid, "title": a.title, "instruction": a.instruction,
            "predicate_src": src, "predicate_sha": sha_of(src), "tz": tz,
            "status": "paused" if a.paused else "active", "state_json": a.state,
            "origin_kind": origin_kind, "origin_id": oid, "origin_thread": thread,
            "origin_label": a.origin_label, "requester_uid": requester,
            "reason": a.reason,
            "not_before": parse_when(a.not_before, tz) if a.not_before else None,
            "not_after": parse_when(a.not_after, tz) if a.not_after else None,
            "max_fires": a.max_fires, "min_interval": a.min_interval,
            "created_at": now, "created_by": a.created_by, "updated_at": now}
    if not legacy:
        cols["origin_transport"] = origin_transport
    conn.execute(f"INSERT INTO tasks({', '.join(cols)}) "
                 f"VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    print(f"\n{tid}  status={'paused' if a.paused else 'active'}  tz={tz}")
    if a.paused:
        print("paused - activate with: sched.py resume " + tid)


def cmd_list(a) -> None:
    conn = connect()
    migrate(conn)
    where, params = "", []
    if a.status == "live":
        where, params = "WHERE status IN (?,?)", list(LIVE_STATUSES)
    elif a.status != "all":
        where, params = "WHERE status=?", [a.status]
    rows = conn.execute(f"SELECT * FROM tasks {where} ORDER BY created_at DESC",
                        params).fetchall()
    if a.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        print("no tasks")
        return
    for r in rows:
        last = fmt_local(r["last_fire_at"], r["tz"]) if r["last_fire_at"] else "never"
        # 20 chars is not arbitrary: it is the longest value in the requester
        # vocabulary (SKILL.md §3). A narrower column truncates a name to something
        # unreadable, which is the exact failure this field exists to prevent.
        by = collapse(r["requester_uid"])[:20]
        print(f"{r['id']}  {r['status']:<9} fires={r['fire_count']:<4} "
              f"last={last:<22} by={by:<20} {collapse(r['title'])[:TITLE_CHARS]}")
        if r["last_error"]:
            print(f"    ⚠ {collapse(r['last_error'])[:160]}")


def cmd_show(a) -> None:
    conn = connect()
    tid = resolve_id(conn, a.id)
    r = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    runs = conn.execute("SELECT * FROM runs WHERE task_id=? ORDER BY fired_at DESC LIMIT ?",
                        (tid, a.runs)).fetchall()
    if a.json:
        print(json.dumps({"task": dict(r), "runs": [dict(x) for x in runs]}, indent=2))
        return
    print(f"{r['id']}  {r['status']}  tz={r['tz']}  rev={r['rev']}")
    print(f"title       {r['title']}")
    print(f"instruction {r['instruction']}")
    _transport = decode_origin(r)[0]
    print(f"origin      {origin_display(r)}"
          + (f" via={_transport}" if _transport else "")
          + (f" thread={r['origin_thread']}" if r["origin_thread"] else ""))
    print(f"requester   {r['requester_uid']}")
    # Printed in full and never elided: the reason is the only thing on this row that
    # answers "should this task still be running", and a reader who has to run a second
    # command to see it will decide without it.
    print(f"reason      {_opt(r, 'reason') or '(none - set one with sched.py set-meta)'}")
    # Printed unconditionally, including when it is empty. An absent line reads as a
    # field this build does not have; "(never)" reads as a fact about this task, which
    # is what it is - the requester and reason are still as `add` wrote them.
    _mb, _ma = _opt(r, "meta_updated_by"), _opt(r, "meta_updated_at")
    print(f"meta set    {_mb} at {_fmt_ts(_ma, r['tz'])}" if _ma is not None else
          "meta set    (never - requester and reason are as `add` wrote them)")
    print(f"fires       {r['fire_count']}" + (f"/{r['max_fires']}" if r["max_fires"] else "")
          + (f"  last={fmt_local(r['last_fire_at'], r['tz'])}" if r["last_fire_at"] else ""))
    print(f"state       {r['state_json']}")
    if r["last_error"]:
        print(f"last error  {r['last_error']} (consecutive={r['error_count']})")
    if r["finished_at"]:
        print(f"finished    {fmt_local(r['finished_at'], r['tz'])} - {r['finished_reason']}")
    print(f"\npredicate ({r['predicate_sha'][:12]}):")
    for ln in r["predicate_src"].splitlines():
        print(f"  {ln}")
    if runs:
        print("\nruns:")
        for x in runs:
            print(f"  {x['run_id']:<6} {fmt_local(x['fired_at'], r['tz'])}  "
                  f"{x['status']:<8} missed={x['missed']}"
                  + (f"  {collapse(x['outcome'])[:80]}" if x["outcome"] else ""))


def cmd_set_meta(a) -> None:
    """Change a task's requester and reason IN PLACE.

    It exists because the alternative - cancel the task and add it back with the fields
    filled in - resets fire history: fire_count, last_fire_at, the predicate's carried
    state and the whole runs table go with the old row. That turns "write down why this
    task exists" into "the task has never fired and its next slot is re-armed from
    now", which loses a day of a daily job and every record of what it has done.
    Nothing here touches the schedule, the predicate, the instruction or the state.
    """
    conn = connect()
    migrate(conn)
    tid = resolve_id(conn, a.id)
    sets, params = [], []
    if a.requester is not None:
        sets.append("requester_uid=?")
        params.append(resolve_requester(a.requester))
    if a.reason is not None:
        # A blank reason here would be a hole straight through `add`'s refusal: the
        # verb that exists to WRITE this field must not be the one that empties it.
        if not a.reason.strip():
            sys.exit(REASON_REFUSAL)
        sets.append("reason=?")
        params.append(a.reason)
    if not sets:
        sys.exit("set-meta: nothing to set - pass --requester and/or --reason")
    # The trail. Written on every set-meta and by nothing else, so a difference the
    # `audit` verb reports has exactly two readings and they are distinguishable: a
    # stamp newer than the baseline means a `set-meta` did it, no stamp at all means
    # something wrote the row behind sched.py's back.
    #
    # ⚠️ `--by` names the ACTOR, and an agent doing this on a human's authorization
    # stamps itself, never the human, so that a row naming a person means that person
    # typed it. The default matches `add --created-by` - a synthetic actor, not a person.
    #
    # ⚠️ THAT IS A CONVENTION, NOT A PROPERTY, AND SAYING SO IS THE POINT. The value is
    # free text: it is not resolved through the requester directory, nothing
    # authenticates the caller, and anything with the database open can write both stamp
    # columns directly - so a stamp can be forged. `audit` therefore treats a stamp as
    # evidence that a set-meta COULD account for a difference, never that one did. The
    # guarantee runs the other way: a stamp UNCHANGED since the baseline beside a changed
    # field is a write no verb made.
    by = collapse(a.by).strip() or "agent"
    sets.append("meta_updated_by=?")
    params.append(by)
    sets.append("meta_updated_at=?")
    params.append(int(time.time()))
    params += [int(time.time()), tid]
    # ⚠️ DELIBERATELY NO `rev=rev+1`, and this is not an oversight to tidy up.
    # `rev` is the daemon's optimistic-concurrency token: it evaluates a task on a
    # snapshot with no lock held, then commits the fire with `WHERE id=? AND rev=?`.
    # A bump landing in that window makes the commit match zero rows, so the fire is
    # ROLLED BACK and never emitted - no run row, no line, no error. Every OTHER verb
    # that bumps `rev` also changes `status`, i.e. the task is MEANT to stop; this is
    # the only one that leaves it active and running, so here the same bump silently
    # drops a wake-up. For a coalescing predicate that costs one tick; for one that
    # does not coalesce, the occurrence is gone for good. The bump buys nothing in
    # return: this UPDATE carries no `AND rev=?` of its own, and the worst a racing
    # fire can do without it is emit one line carrying the pre-backfill reason.
    n = conn.execute(f"UPDATE tasks SET {', '.join(sets)}, updated_at=? "
                     f"WHERE id=?", params).rowcount
    named = [s.split("=")[0] for s in sets if not s.startswith("meta_updated_")]
    print(f"{tid} updated: {', '.join(named)} (by {by})" if n
          else f"{tid} unchanged")


def _set_status(a, status: str, reason: str = None) -> None:
    conn = connect()
    tid = resolve_id(conn, a.id)
    now = int(time.time())
    terminal = status in TERMINAL_STATUSES
    n = conn.execute(
        "UPDATE tasks SET status=?, updated_at=?, finished_at=?, finished_reason=?, "
        "rev=rev+1 WHERE id=? AND status NOT IN ('done','cancelled','archived')",
        (status, now, now if terminal else None, reason, tid)).rowcount
    print(f"{tid} → {status}" if n else f"{tid} unchanged (already terminal)")


def cmd_pause(a) -> None:
    _set_status(a, "paused")


def cmd_cancel(a) -> None:
    _set_status(a, "cancelled", a.reason or "cancelled by request")


def cmd_resume(a) -> None:
    conn = connect()
    tid = resolve_id(conn, a.id)
    r = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    sets, params = ["status='active'", "updated_at=?", "rev=rev+1"], [int(time.time())]
    if a.reset_errors:
        sets += ["error_count=0", "last_error=NULL"]
    if a.rearm:
        # Without this, resuming a task paused for a week fires immediately with
        # missed=7. Sometimes right; usually not.
        sets.append("state_json='{}'")
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params + [tid])
    print(f"{tid} → active" + ("  (re-armed: state cleared)" if a.rearm else ""))
    if not a.rearm and r["last_fire_at"]:
        gap = time.time() - r["last_fire_at"]
        if gap > 86400:
            print(f"⚠ last fired {gap/86400:.1f} days ago - if this task coalesces, its "
                  f"next evaluation will fire once immediately. Use --rearm to skip that.")


def cmd_run_result(a) -> None:
    conn = connect()
    now = int(time.time())
    n = conn.execute(
        "UPDATE runs SET status=?, outcome=?, finished_at=?, "
        "started_at=COALESCE(started_at, ?) WHERE run_id=?",
        (a.status, a.outcome, now, now, a.run_id)).rowcount
    if not n:
        sys.exit(f"no run {a.run_id}")
    print(f"run {a.run_id} → {a.status}")


def cmd_archive(a) -> None:
    conn = connect()
    cutoff = int(time.time()) - a.older_than * 86400
    q = ("SELECT COUNT(*) FROM tasks WHERE status IN ('done','cancelled','failed') "
         "AND finished_at IS NOT NULL AND finished_at < ?")
    n = conn.execute(q, (cutoff,)).fetchone()[0]
    if a.dry_run:
        print(f"would archive {n} task(s) finished more than {a.older_than}d ago")
        return
    conn.execute("UPDATE tasks SET status='archived', updated_at=?, rev=rev+1 "
                 "WHERE status IN ('done','cancelled','failed') AND finished_at IS NOT NULL "
                 "AND finished_at < ?", (int(time.time()), cutoff))
    print(f"archived {n} task(s)")


def cmd_purge(a) -> None:
    conn = connect()
    cutoff = int(time.time()) - a.older_than * 86400
    rows = conn.execute("SELECT id FROM tasks WHERE status='archived' AND finished_at < ?",
                        (cutoff,)).fetchall()
    if not a.yes:
        sys.exit(f"{len(rows)} archived task(s) would be DELETED with their run history. "
                 f"Re-run with --yes. This is the only verb that destroys anything.")
    conn.execute("DELETE FROM tasks WHERE status='archived' AND finished_at < ?", (cutoff,))
    print(f"purged {len(rows)} task(s)")


def cmd_simulate(a) -> None:
    if a.id:
        conn = connect()
        tid = resolve_id(conn, a.id)
        r = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        src, tz, state = r["predicate_src"], r["tz"], json.loads(r["state_json"])
        max_fires, task_floor = r["max_fires"], r["min_interval"]
    else:
        src = a.predicate if a.predicate else open(a.predicate_file).read()
        tz, state, max_fires = a.tz or DEFAULT_TZ, json.loads(a.state), a.max_fires
        task_floor = None

    start = parse_when(a.start, tz) if a.start else time.time()
    end = start + a.days * 86400
    outages = []
    for spec in a.outage or []:
        f, _, t = spec.partition("..")
        outages.append((parse_when(f, tz), parse_when(t, tz)))

    floor = a.min_interval if a.min_interval is not None else (
        task_floor if a.id and task_floor is not None else MIN_INTERVAL_SECS)
    try:
        sim = simulate(src, tz, start, end, step=a.step, state=state, outages=outages,
                       max_fires=max_fires, min_interval=floor)
    except PredicateError as e:
        sys.exit(f"predicate rejected: {e}")
    if a.json:
        out = dict(sim)
        out["fires"] = [{**f, "local": fmt_local(f["at"], tz)} for f in sim["fires"]]
        print(json.dumps(out, indent=2))
        return

    print(f"predicate  sha256:{sha_of(src)[:12]}...  validated")
    print(f"timezone   {tz}")
    print(f"window     {fmt_local(start, tz)} → {fmt_local(end, tz)}   "
          f"step {a.step:g}s   {sim['summary']['evals']} evaluations")
    if outages:
        for f, t in outages:
            print(f"outage     {fmt_local(f, tz)} → {fmt_local(t, tz)} "
                  f"({(t-f)/3600:.0f}h, daemon down)")
    print()
    prev = None
    for i, f in enumerate(sim["fires"], 1):
        delta = f"{(f['at']-prev)/3600:.1f}h" if prev else "-"
        flag = "  ← coalesced" if f["missed"] else ""
        print(f" {i:>3}  {fmt_local(f['at'], tz):<26} Δ{delta:>8}  "
              f"missed={f['missed']}{flag}")
        prev = f["at"]
    s = sim["summary"]
    print(f"\n{len(sim['fires'])} fires / {s['days']:.1f} days ({s['per_day']:.2f}/day)   "
          f"done={'yes' if s['done'] else 'no'}   slowest eval {s['slowest_eval_ms']:.2f} ms")
    print(f"final state {json.dumps(s['final_state'])}")
    if sim["error"]:
        print(f"⚠️  ERROR: {sim['error']}")
    if not sim["fires"]:
        print("⚠️  never fires in this horizon - a dead schedule looks exactly like a "
              "quiet one, and nothing will ever tell you. This is the only place it is visible.")
    if s["per_day"] > FIRES_PER_DAY_WARN:
        print(f"⚠️  {s['per_day']:.1f} fires/day - every fire is a wake-up line in the "
              f"agent's session.")
    if not s["done"] and not max_fires:
        print("⚠️  never returns done - this task runs forever unless --max-fires or "
              "--not-after is set.")
    if s["deferred"]:
        print(f"⚠️  {s['deferred']} evaluation(s) came due inside the {floor:g}s emit "
              f"floor and were deferred. If this cadence is intended, the task needs "
              f"--min-interval below it.")
    total_missed = sum(f["missed"] for f in sim["fires"])
    if total_missed:
        print(f"⚠️  {total_missed} due time(s) folded into fewer fires (coalescing is the "
              f"default; the snippet did not override it).")


# WHAT THE AUDIT COVERS, and the ONE place that decides it. The split is not cosmetic:
# no CLI verb writes `instruction` or `predicate_src`, while `set-meta` writes both META
# fields - so a difference in the first group can never be explained by a verb, and a
# difference in the second can. Reporting them together would let a legitimate
# backfill's stamp sit beside a rewritten instruction and read as its explanation, which
# is the one sentence this verb must never print.
#
# ⚠️ THE PREDICATE IS IN THE FIRST GROUP BECAUSE BOTH HALVES OF A TASK ARE FORGEABLE.
# The instruction is WHAT the agent does; the predicate is WHEN. A raw write to the
# predicate that makes a daily check never fire, or fire every tick, changes what
# the scheduler DOES while leaving every word an operator reads - the title, the
# instruction, the requester, the reason - byte-identical, and a dead schedule is
# indistinguishable from a quiet one from outside. Remove it from this tuple and that
# blind spot comes back silently: nothing goes red, the verb keeps printing OK, and it
# keeps printing OK over a rewritten predicate for ever.
#
# ⚠️ `predicate_sha` IS HERE TOO, AND IT IS NOT REDUNDANT WITH `predicate_src`. It is
# the key `_CODE_CACHE` is keyed on (`load_code`), so in a long-lived daemon it decides
# which compiled object actually RUNS. A raw write to the sha ALONE - to one already
# cached in that process from another task - runs that other task's predicate while
# `predicate_src` still reads honest, i.e. it changes WHEN this task fires and leaves
# nothing for a src-only audit to see. Hashed together, the pair also makes an
# src/sha disagreement a finding, which is the state that write produces.
#
# ⚠️ THE FIRST-GROUP FIELDS HASH TOGETHER, ON PURPOSE. The group is defined by "no verb
# writes this", which is the property the report's annotation turns on, not by which
# field it is; and the operator's next move after any difference here is `show <id>`,
# which prints the instruction AND the predicate in full. A per-field hash column would
# name the field one step earlier and buy nothing after that step.
#
# ⚠️ CHANGING THIS TUPLE IS A DELIBERATE ACT WITH A VISIBLE CONSEQUENCE, WHICH IS WHY
# THE BASELINE CARRIES A `fields=` HEADER: every baseline already on disk stops matching
# and `audit` reports INCONCLUSIVE, naming the rebaseline command. Without that header
# the same change reports every task CHANGED - byte-for-byte what the tampering this
# verb looks for produces, on the one morning a reader most needs the two told apart.
AUDIT_NO_VERB_FIELDS = ("instruction", "predicate_src", "predicate_sha")
AUDIT_META_FIELDS = ("requester_uid", "reason")
AUDIT_FIELDS = AUDIT_NO_VERB_FIELDS + AUDIT_META_FIELDS
# ⚠️ CHANGING THE AUDITED FIELD SET DOES NOT BUMP THIS MARKER, AND BUMPING IT WOULD MAKE
# THE MIGRATION WORSE, NOT SAFER. The `fields=` header is the discriminator; this line
# only says the file belongs to this verb. Bump it and every baseline on disk becomes a
# FOREIGN file: the mismatch degrades from the message that names both field sets to the
# weaker "carries no header" one, and the `--rebaseline` that message tells the operator
# to run is then refused as a takeover, exiting 2 at the one reader who is already
# blocked. Reserve a bump for a change to the LINE FORMAT that this verb's own reader
# could not parse.
AUDIT_MARKER = "sched.py audit baseline v1"


def _audit_hash(row, fields) -> str:
    """sha256[:16] over `fields`, serialised as a JSON array.

    ⚠️ JSON RATHER THAN A JOIN, AND THAT IS THE UNFORGEABILITY ARGUMENT. Any separator
    a value may itself contain lets one field absorb the start of the next: joined on
    `|`, ("a|", "b", "c") and ("a", "|b", "c") produce the identical blob, so an editor
    could move text across a boundary and leave the hash untouched - in the one function
    whose whole job is being unforgeable. JSON escapes every value, so no assignment of
    values can serialise to another assignment's bytes. It also distinguishes NULL from
    the empty string, which a join collapses.
    """
    return hashlib.sha256(
        json.dumps([_opt(row, f) for f in fields], ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _fmt_ts(ts, tz_name) -> str:
    """fmt_local, but a value out of datetime's range renders as itself instead of
    raising.

    ⚠️ THE RAISING VERSION IS A DENIAL OF SERVICE ON THE TAMPER DETECTOR. `meta_updated_at`
    is an integer a raw writer can set to anything and gains nothing else from touching;
    at 99999999999999 `fmt_local` raises `ValueError: year must be in 1..9999`. Out of
    `audit` that kills the whole report - findings accumulate and print at the end, so
    ONE poisoned row silences every other task's difference. Out of `show` it aborts the
    operator's primary investigation verb before it prints the state, the last error, the
    predicate or the run history, for exactly the task under suspicion.
    """
    try:
        return fmt_local(ts, tz_name)
    except (ValueError, OverflowError, OSError, TypeError):
        return f"<unrenderable timestamp {ts!r}>"


def _audit_stamp(row, base_stamp) -> str:
    """Whether a `set-meta` since the baseline can account for a META difference.

    ⚠️ IT COMPARES THE STAMP AGAINST THE BASELINE'S, NEVER MERELY REPORTS THAT ONE
    EXISTS. A row can carry a perfectly legitimate stamp from months ago; printing it
    beside a difference made this morning exonerates that difference, and an audit that
    prints a false exoneration is worse than one that prints nothing - the reader stops
    at the line that says a verb did it.

    ⚠️ AND IT IS EVIDENCE, NOT PROOF. `set-meta` is the only VERB that writes these two
    columns, but anything with the database open can write them directly, so a raw
    writer can forge a stamp. This says "a set-meta could account for it", never "a
    set-meta did it". The audit's real guarantee is the other direction: an UNCHANGED
    stamp beside a changed field is a write that no verb made.
    """
    at = _opt(row, "meta_updated_at")
    if at is None or str(at) == str(base_stamp):
        return "stamp UNCHANGED since the baseline - written around sched.py"
    return (f"set-meta by {_opt(row, 'meta_updated_by')} at "
            f"{_fmt_ts(at, row['tz'])} could account for it")


def _audit_inconclusive(msg: str) -> None:
    """Every path that never reached the tasks ends here, and none of them may print a
    verdict. `2` is not a smaller `1`: `1` means a difference was found, and a traceback
    or a refusal that exits `1` is a finding this verb never made."""
    print(f"AUDIT INCONCLUSIVE: {msg}")
    sys.exit(2)


def _audit_read_baseline(path: str) -> tuple[dict, str]:
    """-> ({task_id: (no-verb-fields hash, meta hash, stamp)}, the declared field set).

    Raises ValueError on anything malformed. The caller turns that into INCONCLUSIVE:
    a baseline with a stray line is a baseline nothing can be compared against, and the
    naive `tid, h, *_ = ln.split()` raises straight out of the verb as exit 1 - the code
    reserved for "a difference was found".
    """
    fields, rows = None, {}
    for n, ln in enumerate(open(path).read().splitlines(), 1):
        if ln.startswith("#"):
            if AUDIT_MARKER in ln:
                # ⚠️ THE HEADER IS READ ONCE, BEFORE ANY ROW, AND A SECOND ONE IS
                # MALFORMED. Taking the LAST marker line instead lets one appended
                # comment line declare a field set the hashes below it were never taken
                # under - so an old baseline is compared anyway and prints a full page
                # of CHANGED carrying the "written around sched.py" accusation. The
                # `fields=` guard is what makes a widening INCONCLUSIVE rather than
                # indistinguishable from tampering; a guard that one appended line
                # disables is not that guard.
                if fields is not None or rows:
                    raise ValueError(
                        f"line {n} is a second '{AUDIT_MARKER}' header"
                        + (" after the rows it would relabel" if rows else "")
                        + ". A baseline declares its field set once, before any row.")
                for tok in ln.split():
                    if tok.startswith("fields="):
                        fields = tok[len("fields="):]
            continue
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) < 4:
            raise ValueError(f"line {n} has {len(parts)} field(s), expected at least 4 "
                             f"(id, instruction+predicate hash, meta hash, stamp"
                             f"[, title]): {ln!r}")
        rows[parts[0]] = (parts[1], parts[2], parts[3])
    return rows, fields


def cmd_audit(a) -> None:
    """Hash every ACTIVE task's instruction, predicate, requester and reason against a
    baseline.

    ⚠️ THREE OUTCOMES, NOT TWO, AND COLLAPSING THEM IS THE FAILURE THIS GUARDS AGAINST.
    `0` every active task matches. `1` something moved, each difference named. `2`
    INCONCLUSIVE - it never reached the tasks: no database, an unreadable or malformed
    baseline, or one whose header does not say it covers the fields this build hashes.
    "Worked", "genuinely broke" and "never ran" are three states, and a check that folds
    the third into the first manufactures the reassuring answer: a reader who sees `OK`
    stops looking. Every failure path here therefore routes through _audit_inconclusive.

    ⚠️ IT OPENS THE DATABASE READ-ONLY AND DOES NOT MIGRATE IT. The verb an operator
    reaches for when they suspect a database has been written behind sched.py's back
    must not take a write lock on it, must not create it if it is missing, and must stay
    usable against a copy or a read-only mount. Nothing here needs the migration: every
    read goes through `_opt`, which is built for a column that is not there.

    ⚠️ IT AUDITS THE FIELDS A REWRITE WOULD CHANGE, NOT THE STAMP. `meta_updated_*` is
    the trail, so hashing it would make every legitimate `set-meta` a difference AND let
    a raw write that also cleared the stamp look tidier than one that did not.
    """
    want = "+".join(AUDIT_FIELDS)
    if not os.path.exists(DB_PATH):
        _audit_inconclusive(f"no database at {DB_PATH}, so nothing was hashed. This is "
                            f"not a clean audit - it is an audit that never ran.")
    try:
        conn = connect(readonly=True)
        live = {r["id"]: r for r in
                conn.execute("SELECT * FROM tasks WHERE status='active'")}
    except SystemExit as e:                       # e.g. migrate's schema-too-new refusal
        _audit_inconclusive(f"{e}")
    except Exception as e:                        # noqa: BLE001 - every one of these
        _audit_inconclusive(                      # means the tasks were never read
            f"cannot read {DB_PATH} ({type(e).__name__}: {e}). A file that is not a "
            f"usable task database is not an empty one.")

    if a.rebaseline:
        # ⚠️ REFUSE TO TAKE OVER A FILE ANOTHER TOOL OWNS. A baseline written by a
        # different auditor has a different field set and no `fields=` guard on its own
        # side, so overwriting it leaves THAT tool reporting every task CHANGED - the
        # exact failure this verb's header exists to prevent, inflicted on a reader who
        # is not even running this verb.
        if os.path.exists(a.baseline) and not a.force:
            try:
                head = open(a.baseline).read(4096)
            except OSError as e:
                _audit_inconclusive(f"cannot read the existing baseline {a.baseline} ({e})")
            if AUDIT_MARKER not in head:
                _audit_inconclusive(
                    f"{a.baseline} exists and was NOT written by this verb (no "
                    f"'{AUDIT_MARKER}' header), so something else compares against it "
                    f"and would read every task as CHANGED afterwards. Point "
                    f"--baseline at a new file, or pass --force to take this one over.")
        hdr = [f"# {AUDIT_MARKER}  fields={want}  "
               f"taken {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}",
               "# <task id>  <instruction+predicate hash>  <requester+reason hash>  "
               "<meta_updated_at>  <title>. Re-run `sched.py audit --baseline <this "
               "file>` at each review; a difference whose stamp is UNCHANGED is a write "
               "that went around sched.py, and it is reported before the task is "
               "followed, never after."]
        body = [f"{tid}  {_audit_hash(r, AUDIT_NO_VERB_FIELDS)}  "
                f"{_audit_hash(r, AUDIT_META_FIELDS)}  "
                f"{_opt(r, 'meta_updated_at') if _opt(r, 'meta_updated_at') is not None else '-'}"
                f"  {collapse(r['title'])}"
                for tid, r in sorted(live.items())]
        # ⚠️ WRITE THEN RENAME. A truncating write that dies half way leaves a header and
        # a partial list, whose missing rows then read as NEW rather than as a broken
        # file - and the retake is the one step of this mechanism no later check undoes.
        tmp = a.baseline + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write("\n".join(hdr + body) + "\n")
            os.replace(tmp, a.baseline)
        except OSError as e:
            _audit_inconclusive(f"cannot write the baseline {a.baseline} ({e}). Nothing "
                                f"was changed.")
        print(f"rebaselined {len(live)} active task(s) -> {a.baseline}")
        return

    try:
        base, fields = _audit_read_baseline(a.baseline)
    except OSError as e:
        _audit_inconclusive(f"cannot read the baseline {a.baseline} ({e}). Create one "
                            f"with: sched.py audit --baseline {a.baseline} --rebaseline")
    except ValueError as e:
        _audit_inconclusive(f"{a.baseline} is malformed: {e}. Nothing was compared.")
    if fields is None:
        _audit_inconclusive(
            f"{a.baseline} carries no '{AUDIT_MARKER}' header, so what its hashes cover "
            f"is unknown and a comparison against them means nothing. Re-take it: "
            f"sched.py audit --baseline {a.baseline} --rebaseline")
    if fields != want:
        _audit_inconclusive(
            f"{a.baseline} covers {fields}; this build hashes {want}. Every task would "
            f"read as a difference, which is indistinguishable from the tampering this "
            f"verb looks for. Confirm the active set is what you expect, then: "
            f"sched.py audit --baseline {a.baseline} --rebaseline")

    bad = []
    for tid, r in sorted(live.items()):
        title = collapse(r["title"])
        if tid not in base:
            bad.append(f"NEW      {tid}  {title}")
            continue
        b_ins, b_meta, b_stamp = base[tid]
        ins, meta = (_audit_hash(r, AUDIT_NO_VERB_FIELDS),
                     _audit_hash(r, AUDIT_META_FIELDS))
        detail = []
        if ins != b_ins:
            # No verb writes `instruction` or `predicate_src`, so no stamp can account
            # for this one and none is offered. Printing the row's stamp here would
            # exonerate the single difference this whole mechanism was built to catch.
            # ⚠️ THE LINE NAMES BOTH FIELDS EVEN THOUGH ONE HASH COVERS THEM. Naming
            # only the instruction would send a reader who is holding a rewritten
            # PREDICATE to read an instruction that is byte-identical, and conclude the
            # verb is broken.
            detail.append(f"instruction/predicate {b_ins} -> {ins} "
                          f"[NO verb writes the instruction or the predicate - written "
                          f"around sched.py; `show` prints both in full]")
        if meta != b_meta:
            detail.append(f"requester/reason {b_meta} -> {meta} "
                          f"[{_audit_stamp(r, b_stamp)}]")
        if detail:
            bad.append(f"CHANGED  {tid}  {title}  " + "; ".join(detail))
    for tid in sorted(base):
        if tid not in live:
            bad.append(f"GONE     {tid}")
    if bad:
        print("\n".join(bad))
        sys.exit(1)
    print(f"OK {len(live)} active task(s) match the baseline ({want})")


def cmd_doctor(a) -> None:
    print(f"config       {CONFIG_FILE}")
    print(f"owner        {OWNER_CONFIG_DIR}  (caller CLAUDE_CONFIG_DIR="
          f"{os.environ.get('CLAUDE_CONFIG_DIR', '<unset>')})")
    print(f"db           {DB_PATH}  exists={os.path.exists(DB_PATH)}")
    print(f"lock         {LOCK_FILE}")
    # The lock FILE outlives the daemon (only the lock is released), and so does the
    # pid written into it: a holder is named only when the flock is held now.
    armed = _daemon_running()
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE) as f:
            recorded = f.read().strip()
        print(f"lock holder  pid {recorded or '<none recorded>'}" if armed else
              "lock holder  none: no process holds the lock"
              + (f" (the file names pid {recorded}, a daemon that is gone)" if recorded else ""))
    print(f"tz default   {DEFAULT_TZ}")
    print(f"tick         {TICK_SECS}s   eval timeout {EVAL_TIMEOUT_SECS}s   "
          f"emit floor {MIN_INTERVAL_SECS}s")
    print(f"armed        {'yes' if armed else 'NO - nothing will fire'}")
    # The directory is a FOREIGN file - typically inside a repository checkout, i.e.
    # exactly the kind of tree that moves under you. Without this line a moved file, a
    # renamed key and a person genuinely absent from the roster are indistinguishable:
    # `add` refuses all three with the same message, and it tells the reader to add a
    # roster entry when the real fault may be the path.
    if REQUESTER_DIRECTORY_FILE or REQUESTER_DIRECTORY_KEY:
        _d = _requester_directory()
        print(f"requesters   {REQUESTER_DIRECTORY_FILE}"
              f" key={REQUESTER_DIRECTORY_KEY} entries={len(_d)}"
              + ("" if _d else "  ⚠ resolves NOTHING (missing file, bad JSON, or a "
                               "key that is not there) - every id-shaped --requester "
                               "will be refused"))
    else:
        print("requesters   (no directory configured; --requester takes a name, and "
              "an id-shaped value is refused)")
    if not os.path.exists(DB_PATH):
        print("\ndatabase does not exist yet - it is created on first `add` or daemon start")
        return
    conn = connect()
    migrate(conn)
    print(f"integrity    {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"schema       v{conn.execute('PRAGMA user_version').fetchone()[0]}")
    print("origins      " + ("Slack only - this database predates transport-neutral "
                             "origins and is never altered" if is_legacy(conn)
                             else "transport-neutral (transport + kind)"))
    print("\ntasks by status:")
    for r in conn.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status"):
        print(f"  {r['status']:<10} {r['n']}")
    pend = conn.execute("SELECT COUNT(*) FROM runs WHERE status='pending'").fetchone()[0]
    lost = conn.execute("SELECT COUNT(*) FROM runs WHERE status='lost'").fetchone()[0]
    print(f"\nruns pending {pend}   lost {lost}")
    if lost:
        print("  ⚠ 'lost' runs fired but were never acknowledged with `run-result` - "
              "work the daemon announced and nobody recorded doing.")


def _daemon_running() -> bool:
    """Whether a process holds the flock on LOCK_FILE now: a non-blocking attempt
    to take it. installation/check's lock_state() makes the same attempt."""
    if not os.path.exists(LOCK_FILE):
        return False
    fd = os.open(LOCK_FILE, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sched.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="create a task (dry-runs the predicate first)")
    a.add_argument("--title", required=True)
    a.add_argument("--instruction", required=True,
                   help="what the agent must DO when this fires - verbatim, self-contained")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--predicate-file")
    g.add_argument("--predicate")
    a.add_argument("--origin", required=True,
                   help="session, <transport>:<kind>:<conversation>[:<thread>] (kind "
                        "channel or dm), slack:<channel id> or dm:<id>")
    a.add_argument("--thread", help="thread id; always stored with its conversation")
    a.add_argument("--origin-label")
    a.add_argument("--requester", required=True, help=_REQUESTER_HELP)
    # Deliberately NOT argparse-required: cmd_add refuses a missing reason itself, with
    # the three questions spelled out. argparse's "the following arguments are required:
    # --reason" is a correct message that teaches nothing, and a field whose prompt does
    # not say what good looks like gets filled with "Ada asked for it" - which is the
    # useless answer this field exists to replace. The refusal is the documentation, and
    # it reaches the one reader who is already blocked.
    a.add_argument("--reason", help="REQUIRED. " + _REASON_HELP)
    a.add_argument("--tz")
    a.add_argument("--state", default="{}")
    a.add_argument("--max-fires", type=int)
    a.add_argument("--min-interval", type=float)
    a.add_argument("--not-before")
    a.add_argument("--not-after")
    a.add_argument("--paused", action="store_true",
                   help="insert paused - for a schedule whose reading needs confirming")
    a.add_argument("--created-by", default="agent")
    a.add_argument("--simulate-days", type=int, default=ADD_SIMULATE_DAYS)
    a.add_argument("--step", type=float, default=60.0)
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_add)

    a = sub.add_parser("list")
    a.add_argument("--status", default="live",
                   choices=["live", "all", "active", "paused", "done", "cancelled",
                            "failed", "archived"])
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_list)

    a = sub.add_parser("show")
    a.add_argument("id")
    a.add_argument("--runs", type=int, default=10)
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_show)

    a = sub.add_parser("set-meta", help="change a task's requester/reason in place "
                                        "(keeps its fire history; cancel+add would not)")
    a.add_argument("id")
    a.add_argument("--requester", help=_REQUESTER_HELP)
    a.add_argument("--reason", help=_REASON_HELP)
    a.add_argument("--by", default="agent",
                   help="who is making this change - recorded as meta_updated_by "
                        "alongside the time. Name the ACTOR: an agent editing a row on "
                        "a human's authorization stamps ITSELF, so that a row naming a "
                        "person means that person typed it. ⚠️ NOT the `by=` that "
                        "`list` and the wake-up line print - that is the REQUESTER, and "
                        "--requester is what changes it. Default: agent")
    a.set_defaults(fn=cmd_set_meta)

    a = sub.add_parser("pause"); a.add_argument("id"); a.set_defaults(fn=cmd_pause)

    a = sub.add_parser("resume")
    a.add_argument("id")
    a.add_argument("--reset-errors", action="store_true")
    a.add_argument("--rearm", action="store_true", help="clear state so it does not "
                                                        "fire immediately on resume")
    a.set_defaults(fn=cmd_resume)

    a = sub.add_parser("cancel"); a.add_argument("id"); a.add_argument("--reason")
    a.set_defaults(fn=cmd_cancel)

    a = sub.add_parser("run-result", help="record what happened when a fire was executed")
    a.add_argument("run_id", type=int)
    a.add_argument("--status", required=True, choices=["ok", "failed", "skipped"])
    a.add_argument("--outcome")
    a.set_defaults(fn=cmd_run_result)

    a = sub.add_parser("archive")
    a.add_argument("--older-than", type=int, default=AUTO_ARCHIVE_DAYS)
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(fn=cmd_archive)

    a = sub.add_parser("purge")
    a.add_argument("--older-than", type=int, default=PURGE_DAYS)
    a.add_argument("--yes", action="store_true")
    a.set_defaults(fn=cmd_purge)

    a = sub.add_parser("simulate", help="dry-run a predicate over a fake clock")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--predicate-file")
    g.add_argument("--predicate")
    a.add_argument("--start")
    a.add_argument("--days", type=float, default=30)
    a.add_argument("--step", type=float, default=60.0)
    a.add_argument("--tz")
    a.add_argument("--state", default="{}")
    a.add_argument("--max-fires", type=int)
    a.add_argument("--min-interval", type=float,
                   help="model the emit floor this task will get; must be BELOW the "
                        "intended cadence or fires are deferred")
    a.add_argument("--outage", action="append",
                   help="FROM..TO - the daemon is down; proves coalescing")
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_simulate)

    a = sub.add_parser("audit", help="hash every ACTIVE task's instruction, predicate, "
                                     "requester and reason against a baseline file")
    a.add_argument("--baseline", required=True,
                   help="the baseline file to compare against (or to write with "
                        "--rebaseline). No default: the file belongs to the deployment, "
                        "not to this skill")
    a.add_argument("--rebaseline", action="store_true",
                   help="overwrite the baseline with the CURRENT active set. Only after "
                        "every difference has a visible sched.py verb behind it - "
                        "rebaselining an unexplained difference is how it becomes the "
                        "new normal")
    a.add_argument("--force", action="store_true",
                   help="with --rebaseline: take over a baseline file written by some "
                        "OTHER tool. Refused by default, because overwriting it leaves "
                        "that tool reading every task as changed")
    a.set_defaults(fn=cmd_audit)

    a = sub.add_parser("doctor"); a.set_defaults(fn=cmd_doctor)
    return p


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    # Bare invocation is the tick loop and `--once` is a single tick. Every OTHER
    # leading-dash argument goes to argparse, so `--help` prints the help it advertises
    # instead of silently arming a daemon - which is what a reader who has just been
    # refused by a flag reaches for.
    if not argv or argv[0] == "--once":
        run_daemon(once="--once" in argv)
        return
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        sys.exit(2)
    args.fn(args)


if __name__ == "__main__":
    main()
