#!/usr/bin/env python3
"""Offline regression guard for sched.py.

No network, no Slack, no wall-clock sleeping - every clock in the daemon is an
argument, which is exactly what makes this possible. The only I/O is a temporary
SQLite file.

Cases marked TEETH assert that a NAIVE implementation fails. They are the ones worth
reading: each names the bug it exists to prevent, because a test whose failure message
does not say what broke is a test people delete.

Run:  python3 <skill dir>/sched.test.py
"""

import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

_failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sched.py")
_EXAMPLE_CONFIG = os.path.join(os.path.dirname(_SCRIPT), "config.example.json")

# Resolve the module against the EXAMPLE config, unconditionally, and drop every env
# override before the import. sched.py reads its config at IMPORT time, so an ambient
# SCHED_CONFIG or SCHED_DB would point this suite at whichever live install happened to
# run it - the suite would then pass or fail depending on whose session invoked it, and
# a stray SCHED_DB would aim the CLI section at a real database. Forcing it here is what
# keeps the guard offline, hermetic and identical on every machine, and it is why the
# skill ships no config.json of its own: there is no per-install file for the tests to
# depend on. Sections 10 and 11 set SCHED_CONFIG per subprocess anyway.
for _k in ("SCHED_CONFIG", "SCHED_DB", "SCHED_TICK_SECS", "SCHED_EVAL_TIMEOUT_SECS"):
    os.environ.pop(_k, None)
os.environ["SCHED_CONFIG"] = _EXAMPLE_CONFIG

_spec = importlib.util.spec_from_file_location("sched_mod", _SCRIPT)
s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s)

# The SCHEMA text sched.py shipped before origins carried a transport, VERBATIM. Six
# live databases carry exactly this table, and the code must keep reading and writing
# them without altering them. ⚠️ IT IS A SECOND, INDEPENDENT STATEMENT OF THAT FORMAT ON
# PURPOSE: derived from s.SCHEMA it would agree with any future edit to the fresh schema,
# and could never notice a change that breaks the databases already in the field.
# Sections 13(d), 14 and 16 build their pre-existing databases from it.
LEGACY_SCHEMA = """
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
                  CHECK (origin_kind IN ('slack_channel','slack_dm','slack_thread','session')),
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

# THE SUITE'S OWN FLEET TREE. sched.py reads the fleet's chat transports through
# fleetlib, from the fleet tree it lives in (realpath of its own file, three parents
# up). So the suite builds one in a tempdir: a copy of this sched.py, a copy of the
# real lib/fleetlib, and three synthetic transport descriptors - two working, one
# placeholder - so its verdict never depends on which transport skills the checkout
# running it carries. Every CLI case runs that copy (_SCRIPT_FT), and so does every
# mutant; the in-process module `s` is the real file, used only where no registry is
# needed. Without the copy of fleetlib there is nothing to run against: that is a
# suite that cannot reach its subject, so it stops here rather than reporting on it.
_REAL_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.realpath(_SCRIPT))))), "lib")
if not os.path.isfile(os.path.join(_REAL_LIB, "fleetlib", "transports.py")):
    print(f"[FAIL] NOT RUN: no fleetlib at {_REAL_LIB} - this suite runs sched.py inside "
          f"a copy of the fleet tree, and there is no library to copy")
    sys.exit(1)
# fleetlib honours a TEST-ONLY override that points the registry at another directory.
# Inherited from whatever ran this suite, it would replace the descriptors below with
# that directory's and every origin case would measure someone else's fixtures - so it
# is dropped for this process and every subprocess it starts.
os.environ.pop("FLEET_TRANSPORTS_DIR", None)
_ft_tmp = tempfile.TemporaryDirectory()
_FT = os.path.join(_ft_tmp.name, "fleet")
shutil.copytree(os.path.join(_REAL_LIB, "fleetlib"), os.path.join(_FT, "lib", "fleetlib"),
                ignore=shutil.ignore_patterns("__pycache__", "*.test.py"))
FIXTURE_TRANSPORTS = {
    "slack-communication": {
        "schema": 1, "name": "slack", "status": "working", "line_prefix": "SLACK",
        "kinds": ["channel", "dm", "thread"],
        "ids": {"user": "^U[A-Z0-9]{6,}$", "conversation": "^[CDG][A-Z0-9]{2,20}$",
                "message": "^[0-9]{9,10}\\.[0-9]{6}$"},
        "watch": {"script": "watch.py", "job": "slack-watch",
                  "config_env": "SLACK_WATCH_CONFIG", "follow_include": "^SLACK "}},
    "chatx-communication": {
        "schema": 1, "name": "chatx", "status": "working", "line_prefix": "CHATX",
        "kinds": ["channel", "dm", "thread"],
        "ids": {"user": "^X[0-9]{4,}$", "conversation": "^XC[0-9]{3,}$",
                "message": "^[0-9]{1,12}$"},
        "watch": {"script": "watch.py", "job": "chatx-watch",
                  "config_env": "CHATX_WATCH_CONFIG", "follow_include": "^CHATX "}},
    "discord-communication": {
        "schema": 1, "name": "discord", "status": "placeholder", "line_prefix": "DISCORD",
        "kinds": ["channel", "dm", "thread"],
        "ids": {"user": "^[0-9]{17,20}$", "conversation": "^[0-9]{17,20}$",
                "message": "^[0-9]{17,20}$"},
        "watch": {"script": "watch.py", "job": "discord-watch",
                  "config_env": "DISCORD_WATCH_CONFIG", "follow_include": "^DISCORD "}},
}
for _skill, _desc in FIXTURE_TRANSPORTS.items():
    _d = os.path.join(_FT, ".claude", "skills", _skill)
    os.makedirs(_d)
    with open(os.path.join(_d, "transport.json"), "w") as _f:
        json.dump(_desc, _f, indent=2)
    with open(os.path.join(_d, "SKILL.md"), "w") as _f:
        _f.write(f"---\nname: {_skill}\nversion: 1\ndescription: >\n  fixture transport "
                 f"for sched.test.py\nrequires_install: false\n---\n")
    with open(os.path.join(_d, "watch.py"), "w") as _f:
        _f.write("import sys\nsys.exit(2)\n")
_SCRIPT_FT = os.path.join(_FT, ".claude", "skills", "scheduled-tasks", "sched.py")
os.makedirs(os.path.dirname(_SCRIPT_FT))
shutil.copy2(_SCRIPT, _SCRIPT_FT)

# A TEST FIXTURE, not a deployment setting. The suite needs a timezone that actually
# observes DST, because the sharpest tests here are the ones proving a 09:00 job stays
# at 09:00 across both transitions. Swapping this for UTC would make those tests pass
# while testing nothing. Change it only to another DST-observing zone.
TZ = "Europe/Berlin"


def mkrow(src, state=None, tz=TZ, **extra):
    row = {"predicate_sha": s.sha_of(src), "predicate_src": src, "tz": tz,
           "state_json": json.dumps(state or {})}
    row.update(extra)
    return row


# Predicates reused across sections. These are the templates SKILL.md ships, so a
# change that breaks them breaks the documentation too.
DAILY = """
HOURS = (9,)
ARM_LOOKBACK = 8 * 86400

def skip_day(d):
    return False

def should_fire(now, state):
    last = state.get("last_due", 0)
    if not last:
        prev = due_slots(now - ARM_LOOKBACK, now, HOURS, TZ, skip=skip_day)
        return {"fire": False, "state": {"last_due": prev[-1] if prev else now}}
    slots = due_slots(last, now, HOURS, TZ, skip=skip_day)
    if not slots:
        return {"fire": False, "state": state}
    return {"fire": True, "missed": len(slots) - 1, "state": {"last_due": slots[-1]}}
"""

HELLO5 = """
INTERVAL = 60
TOTAL = 5

def should_fire(now, state):
    sent = state.get("sent", 0)
    nxt = state.get("next", now)
    if now < nxt:
        return {"fire": False, "state": state}
    # Re-anchor on `now`, do NOT count the missed boundaries as sends: "5 times, a
    # minute apart" asked for FIVE hellos. Downtime delays them; it must not eat them.
    missed = int((now - nxt) // INTERVAL)
    sent += 1
    return {"fire": True, "missed": missed,
            "state": {"sent": sent, "next": now + INTERVAL},
            "done": sent >= TOTAL}
"""

LINK = """
HOURS = (9, 21)
ARM_LOOKBACK = 40 * 86400

def skip_day(d):
    if is_leap(d.year):
        return True
    if d.weekday() == MON and 8 <= d.day <= 14:
        return True
    return False

def should_fire(now, state):
    last = state.get("last_due", 0)
    if not last:
        prev = due_slots(now - ARM_LOOKBACK, now, HOURS, TZ, skip=skip_day)
        return {"fire": False, "state": {"last_due": prev[-1] if prev else now}}
    slots = due_slots(last, now, HOURS, TZ, skip=skip_day)
    if not slots:
        return {"fire": False, "state": state}
    return {"fire": True, "missed": len(slots) - 1, "state": {"last_due": slots[-1]}}
"""

ALWAYS = "def should_fire(now, state):\n    return True\n"


def ts(iso, tz=TZ):
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo(tz)).timestamp()


# === 1. Result normalization ================================================
print("\n--- 1. result normalization ---")

check("bare True normalizes to fire with state unchanged",
      s.normalize_result(True, {"a": 1}).fire is True
      and s.normalize_result(True, {"a": 1}).state == {"a": 1})
check("(True, state) normalizes",
      s.normalize_result((True, {"b": 2}), {}).state == {"b": 2})
check("dict form carries missed/done/note",
      (lambda r: r.fire and r.missed == 3 and r.done and r.note == "x")(
          s.normalize_result({"fire": True, "missed": 3, "done": True, "note": "x"}, {})))


def rejects(raw, prev=None):
    try:
        s.normalize_result(raw, prev or {})
        return False
    except s.PredicateError:
        return True


def _msg_of(raw):
    try:
        s.normalize_result(raw, {})
        return ""
    except s.PredicateError as e:
        return str(e)


check("dict without 'fire' is rejected", rejects({"state": {}}))
check("unknown result key is rejected", rejects({"fire": True, "fire_at": 1}))
check("non-dict state is rejected", rejects({"fire": False, "state": [1, 2]}))
check("bare string return is rejected", rejects("yes"))
check("negative missed is rejected", rejects({"fire": True, "missed": -1}))
# TEETH - a set survives json.dumps as a list and comes back as a list NEXT tick,
# silently changing what the predicate does on day two. Catch it on day one.
check("TEETH: state containing a set is rejected at the FIRST evaluation",
      rejects({"fire": True, "state": {"seen": {1, 2}}}))
check("rejection names the offending key",
      "seen" in _msg_of({"fire": True, "state": {"seen": {1}}}),
      _msg_of({"fire": True, "state": {"seen": {1}}}))
check("shape errors are immediate (no three strikes)",
      s.PredicateError.immediate is True and s.PredicateTimeout.immediate is False)


# === 2. The three shipped predicates ========================================
print("\n--- 2. the three shipped predicates ---")

r = s.simulate(HELLO5, TZ, 1000.0, 1000.0 + 600, step=5, max_fires=5, min_interval=0)
check("(a) hello fires exactly 5 times", len(r["fires"]) == 5, f"got {len(r['fires'])}")
check("(a) hello fires 60s apart",
      all(abs(r["fires"][i + 1]["at"] - r["fires"][i]["at"] - 60) < 6 for i in range(4)),
      str([f["at"] - 1000 for f in r["fires"]]))
check("(a) hello reports done on the 5th", r["fires"][-1]["done"] is True)

r = s.simulate(DAILY, TZ, ts("2026-08-04T12:00"), ts("2026-08-09T12:00"), step=300)
check("(b) daily fires once per day", len(r["fires"]) == 5, f"got {len(r['fires'])}")
check("(b) daily fires at 09:00 local",
      all(s.fmt_local(f["at"], TZ).endswith("09:00") for f in r["fires"]),
      str([s.fmt_local(f["at"], TZ) for f in r["fires"]]))

# TEETH - a `last + 86400` implementation drifts to 08:00 or 10:00 across a DST
# transition. The symptom is a report arriving an hour early twice a year, which reads
# as flakiness rather than as a bug, so nobody files it.
r = s.simulate(DAILY, TZ, ts("2026-10-22T12:00"), ts("2026-10-27T12:00"), step=300)
check("TEETH: (b) holds 09:00 LOCAL across the DST fall-back",
      all(s.fmt_local(f["at"], TZ).endswith("09:00") for f in r["fires"]),
      str([s.fmt_local(f["at"], TZ) for f in r["fires"]]))
r = s.simulate(DAILY, TZ, ts("2026-03-26T12:00"), ts("2026-03-31T12:00"), step=300)
check("TEETH: (b) holds 09:00 LOCAL across the DST spring-forward",
      all(s.fmt_local(f["at"], TZ).endswith("09:00") for f in r["fires"]),
      str([s.fmt_local(f["at"], TZ) for f in r["fires"]]))

r = s.simulate(LINK, TZ, ts("2027-01-04T00:00"), ts("2027-01-20T00:00"), step=1800)
days = sorted({s.fmt_local(f["at"], TZ)[:10] for f in r["fires"]})
# TEETH - `d.day <= 7` selects the FIRST Monday. Only 8 <= day <= 14 is the second.
check("TEETH: (c) skips the SECOND Monday (11 Jan 2027), not the first",
      "Mon 11 Jan" not in " ".join(days) and "Mon 04 Jan" in " ".join(days),
      str(days))
check("(c) still fires on the 3rd Monday (18 Jan 2027)", "Mon 18 Jan" in " ".join(days))
check("(c) fires twice a day on a normal day",
      sum(1 for f in r["fires"] if s.fmt_local(f["at"], TZ).startswith("Tue 05 Jan")) == 2)
r = s.simulate(LINK, TZ, ts("2028-03-01T00:00"), ts("2028-03-21T00:00"), step=3600)
check("(c) fires ZERO times in a leap year", len(r["fires"]) == 0, f"got {len(r['fires'])}")


# === 3. Coalescing across a simulated outage ================================
print("\n--- 3. coalescing across an outage ---")

out = [(ts("2026-08-05T12:00"), ts("2026-08-08T12:00"))]
r = s.simulate(DAILY, TZ, ts("2026-08-04T12:00"), ts("2026-08-09T00:00"), step=300,
               outages=out)
after = [f for f in r["fires"] if f["at"] > ts("2026-08-08T12:00")]
# TEETH - a naive implementation does one of two wrong things: fires three times (a
# burst of three identical reports into a Slack channel) or fires once with missed=0
# (silent loss, so nobody knows the machine was down). Both are asserted against.
check("TEETH: a 3-due-time outage produces exactly ONE fire on return",
      len(after) == 1, f"got {len(after)} fires after the outage")
check("TEETH: the coalesced fire reports missed=2 (3 slots folded), not 0",
      after and after[0]["missed"] == 2, str([f["missed"] for f in after]))

r = s.simulate(DAILY, TZ, ts("2026-08-04T12:00"), ts("2026-08-07T00:00"), step=300,
               outages=[(ts("2026-08-05T13:00"), ts("2026-08-05T18:00"))])
check("a sub-period outage coalesces nothing (missed stays 0)",
      all(f["missed"] == 0 for f in r["fires"]), str([f["missed"] for f in r["fires"]]))

r = s.simulate(HELLO5, TZ, 1000.0, 1000.0 + 900, step=5, max_fires=5, min_interval=0,
               outages=[(1000.0 + 100, 1000.0 + 300)])
check("an outage inside a counted task still totals 5 hellos",
      len(r["fires"]) == 5, f"got {len(r['fires'])}")


# === 4. Purity ==============================================================
print("\n--- 4. purity ---")

a1 = s.simulate(DAILY, TZ, ts("2026-08-04T12:00"), ts("2026-08-09T12:00"), step=300)
a2 = s.simulate(DAILY, TZ, ts("2026-08-04T12:00"), ts("2026-08-09T12:00"), step=300)
check("the same window simulated twice gives identical fires",
      [f["at"] for f in a1["fires"]] == [f["at"] for f in a2["fires"]])

# TEETH - this pins the "cache the CODE OBJECT, re-exec the module body" decision.
# Caching the resulting function instead would let module-level globals accumulate
# state the DB never sees, so the daemon and the simulator would disagree - and the
# simulator is the only pre-flight check there is.
MUTATOR = """
SEEN = []

def should_fire(now, state):
    SEEN.append(now)
    return {"fire": len(SEEN) > 2, "state": state}
"""
b1 = s.simulate(MUTATOR, TZ, 0.0, 50.0, step=10, min_interval=0)
b2 = s.simulate(MUTATOR, TZ, 0.0, 50.0, step=10, min_interval=0)
check("TEETH: a module-level global does not leak between evaluations",
      len(b1["fires"]) == 0 and len(b2["fires"]) == 0,
      f"run1={len(b1['fires'])} run2={len(b2['fires'])}")

CLOCK = "def should_fire(now, state):\n    return {'fire': datetime.now() > now, 'state': state}\n"
r = s.simulate(CLOCK, TZ, 0.0, 30.0, step=10)
check("a predicate cannot reach the real clock", r["error"] is not None, str(r["error"]))


# === 5. Sandbox - all TEETH =================================================
print("\n--- 5. sandbox ---")


def rejected(src):
    try:
        s.validate_predicate(src)
        return False
    except s.PredicateError:
        return True


ok_tail = "\ndef should_fire(now, state):\n    return False\n"
check("TEETH: import is rejected", rejected("import os" + ok_tail))
check("TEETH: from-import is rejected", rejected("from os import path" + ok_tail))
check("TEETH: __import__ is rejected (underscore rule)",
      rejected("def should_fire(now, state):\n    return __import__('os')\n"))
check("TEETH: ().__class__ escape is rejected (underscore rule)",
      rejected("def should_fire(now, state):\n    return ().__class__.__base__\n"))
check("TEETH: getattr is rejected (denylist closes the string-built dunder)",
      rejected("def should_fire(now, state):\n    return getattr(now, 'x')\n"))
check("TEETH: open is rejected", rejected("def should_fire(now, state):\n    return open('/etc/passwd')\n"))
# TEETH - the one that is not obvious. A bare handler swallows the SIGALRM exception
# and loops forever, taking the daemon's main loop with it; no timer-based guard
# survives it. Banning Try at write time is the only in-process fix.
check("TEETH: try/except is rejected (it would swallow the eval timeout)",
      rejected("def should_fire(now, state):\n    try:\n        pass\n    except:\n        pass\n    return False\n"))
check("TEETH: class definitions are rejected", rejected("class C:\n    pass" + ok_tail))
check("a snippet with no should_fire is rejected", rejected("def nope(now, state):\n    return False\n"))
check("a syntax error is rejected as PredicateError, not SyntaxError",
      rejected("def should_fire(now, state)\n    return False\n"))
check("the ordinary templates all validate",
      not rejected(DAILY) and not rejected(HELLO5) and not rejected(LINK))
# HONESTY CHECK, deliberately asserting the documented LIMITATION. If this ever starts
# being rejected, good - but nobody may read the sandbox as a security boundary on the
# strength of the checks above.
check("DOCUMENTED LIMIT: a runtime-built dunder in a format string is NOT caught",
      not rejected('def should_fire(now, state):\n    return "{0.__class__}".format(())\n'),
      "in-process CPython sandboxes do not confine a determined author - SKILL.md says so")


# === 6. Timeout =============================================================
print("\n--- 6. evaluation timeout ---")

t0 = time.monotonic()
try:
    s.evaluate(mkrow("def should_fire(now, state):\n    while True:\n        pass\n"), 0.0,
               timeout=0.2)
    timed_out = False
except s.PredicateTimeout:
    timed_out = True
elapsed = time.monotonic() - t0
check("an infinite loop raises PredicateTimeout", timed_out)
check("it is killed near the budget, not after it runs to completion",
      elapsed < 2.0, f"{elapsed:.2f}s")

# TEETH - the classic signal.alarm bug: a timer left armed after a slow-but-successful
# evaluation fires during the NEXT task and fails an innocent one.
with contextlib.suppress(s.PredicateTimeout):
    s.evaluate(mkrow("def should_fire(now, state):\n    while True:\n        pass\n"), 0.0,
               timeout=0.1)
fast_ok = True
try:
    for _ in range(20):
        s.evaluate(mkrow(DAILY), time.time(), timeout=0.25)
except s.PredicateTimeout:
    fast_ok = False
check("TEETH: the timer is disarmed afterwards - a later fast predicate survives", fast_ok)

t0 = time.monotonic()
s.evaluate(mkrow("def should_fire(now, state):\n"
                 "    x = sum(range(200000))\n    return {'fire': False, 'state': state}\n"),
           0.0, timeout=1.0)
check("a slow-but-under-budget predicate is NOT killed", time.monotonic() - t0 < 1.0)


# === 7. Database and the tick ===============================================
print("\n--- 7. database and the tick ---")

_tmp = tempfile.TemporaryDirectory()
_db = os.path.join(_tmp.name, "sub", "tasks.db")
s.DB_PATH = _db
conn = s.connect(_db)
s.migrate(conn)
check("first run creates the schema", conn.execute("PRAGMA user_version").fetchone()[0] == 1)
check("WAL is on", conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal")
s.migrate(conn)
check("re-migrating is a no-op", conn.execute("PRAGMA user_version").fetchone()[0] == 1)
check("the db directory is created 0700",
      oct(os.stat(os.path.dirname(_db)).st_mode)[-3:] == "700",
      oct(os.stat(os.path.dirname(_db)).st_mode)[-3:])


def add_task(src, tid, **kw):
    now = int(time.time())
    cols = dict(id=tid, title="T " + tid, instruction="do the thing",
                predicate_src=src, predicate_sha=s.sha_of(src), tz=TZ,
                status="active", state_json="{}", origin_kind="channel",
                origin_transport="slack", origin_id="C123", origin_thread=None, origin_label="#ops",
                requester_uid="Ada", reason="so the thing happens",
                not_before=None, not_after=None, max_fires=None,
                min_interval=0.0, created_at=now, created_by="test", updated_at=now)
    cols.update(kw)
    conn.execute(f"INSERT INTO tasks({','.join(cols)}) "
                 f"VALUES({','.join('?' * len(cols))})", list(cols.values()))


add_task(ALWAYS, "tsk_a", min_interval=0.0)
lines = s.run_tick(conn, 1000.0)
check("a due task produces exactly one emit line", len(lines) == 1, str(lines))
check("the line carries the SCHED due sentinel and the task id",
      lines and lines[0].startswith("SCHED due [tsk_a] run="), str(lines))
check("a runs row was inserted pending",
      conn.execute("SELECT status FROM runs WHERE task_id='tsk_a'").fetchone()[0] == "pending")
check("fire_count advanced",
      conn.execute("SELECT fire_count FROM tasks WHERE id='tsk_a'").fetchone()[0] == 1)

# TEETH - the emit floor is enforced by the DAEMON regardless of what the predicate
# returns. Without it, one snippet stuck at fire=True injects a wake-up line every
# single tick and makes the agent's session unusable.
conn.execute("UPDATE tasks SET min_interval=30 WHERE id='tsk_a'")
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    lines = s.run_tick(conn, 1005.0)
check("TEETH: a second fire inside min_interval is suppressed by the daemon",
      len(lines) == 0, str(lines))
lines = s.run_tick(conn, 1100.0)
check("...and allowed again once the floor has passed", len(lines) == 1, str(lines))

# TEETH - the cancel race. Without `WHERE rev=?`, a cancel landing between evaluation
# and commit still emits, and real work gets done on a task a human just killed.
add_task(ALWAYS, "tsk_race", min_interval=0.0)
row = conn.execute("SELECT * FROM tasks WHERE id='tsk_race'").fetchone()
conn.execute("UPDATE tasks SET rev=rev+1, status='cancelled' WHERE id='tsk_race'")
res = s.EvalResult(True, {})
check("TEETH: a cancel racing a fire produces NO emit",
      s._commit_fire(conn, row, res, 2000.0) is None)
check("...and no run row for the cancelled task",
      conn.execute("SELECT COUNT(*) FROM runs WHERE task_id='tsk_race'").fetchone()[0] == 0)

add_task(ALWAYS, "tsk_dup", min_interval=0.0)
row = conn.execute("SELECT * FROM tasks WHERE id='tsk_dup'").fetchone()
s._commit_fire(conn, row, s.EvalResult(True, {}), 3000.0)
row2 = conn.execute("SELECT * FROM tasks WHERE id='tsk_dup'").fetchone()
check("a duplicate (task, fired_at) is a no-op, not a second wake-up",
      s._commit_fire(conn, row2, s.EvalResult(True, {}), 3000.0) is None)

# TEETH - surviving the loop is not enough: the healthy task must still have been served.
add_task("def should_fire(now, state):\n    return {'fire': 'yes'}\n", "tsk_bad")
add_task(ALWAYS, "tsk_good", min_interval=0.0)
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    lines = s.run_tick(conn, 5000.0)
check("TEETH: a task with a broken predicate does not stop the healthy one firing",
      any("tsk_good" in ln for ln in lines), str(lines))
bad = conn.execute("SELECT status, error_count FROM tasks WHERE id='tsk_bad'").fetchone()
check("a bad RETURN SHAPE fails the task on strike one",
      bad["status"] == "failed", f"status={bad['status']} errors={bad['error_count']}")
check("the failure is logged to stderr with the SCHED-ERROR prefix",
      "SCHED-ERROR" in _err.getvalue(), _err.getvalue()[:120])

add_task("def should_fire(now, state):\n    while True:\n        pass\n", "tsk_slow")
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    for i in range(3):
        s.run_tick(conn, 6000.0 + i)
slow = conn.execute("SELECT status, error_count FROM tasks WHERE id='tsk_slow'").fetchone()
check("a repeatedly timing-out predicate latches to failed after max_errors",
      slow["status"] == "failed", f"status={slow['status']} errors={slow['error_count']}")
check("state is NOT written on a failing evaluation",
      conn.execute("SELECT state_json FROM tasks WHERE id='tsk_slow'").fetchone()[0] == "{}")

add_task(DAILY, "tsk_idle")
before = conn.execute("SELECT rev FROM tasks WHERE id='tsk_idle'").fetchone()[0]
s.run_tick(conn, time.time())          # first eval arms it - state changes, so a write
mid = conn.execute("SELECT rev FROM tasks WHERE id='tsk_idle'").fetchone()[0]
s.run_tick(conn, time.time() + 1)      # second eval changes nothing
after_rev = conn.execute("SELECT rev FROM tasks WHERE id='tsk_idle'").fetchone()[0]
check("an idle tick writes nothing (state unchanged ⇒ no UPDATE)",
      mid > before and after_rev == mid, f"{before} → {mid} → {after_rev}")

add_task(ALWAYS, "tsk_exp", not_after=100)
s.run_tick(conn, 200.0)
check("not_after closes a task without calling its predicate",
      conn.execute("SELECT status FROM tasks WHERE id='tsk_exp'").fetchone()[0] == "done")

add_task(ALWAYS, "tsk_cap", max_fires=2, min_interval=0.0)
s.run_tick(conn, 7000.0)
s.run_tick(conn, 7001.0)
cap = conn.execute("SELECT status, fire_count FROM tasks WHERE id='tsk_cap'").fetchone()
check("max_fires closes the task even though the predicate never says done",
      cap["status"] == "done" and cap["fire_count"] == 2, dict(cap))


# === 8. Emit format =========================================================
print("\n--- 8. emit format ---")

erow = {"id": "tsk_x", "title": "Competitor  research\nweekly", "instruction": "do it",
        "origin_kind": "slack_channel", "origin_id": "C123", "origin_thread": None,
        "origin_label": "#ops", "requester_uid": "Ada", "reason": "the digest is the only\nweekly signal"}
line = s.format_emit(erow, 417, 0)
check("channel origin renders id(label)", "origin=C123(#ops)" in line, line)
check("title newlines are collapsed", "research weekly" in line, line)
check("run id is on the line", "run=417" in line, line)
check("no thread token when the task has no thread", "thread=" not in line, line)
erow2 = dict(erow, origin_thread="1784577731.070209")
check("thread is emitted WITH its channel (targeting trap)",
      "origin=C123(#ops) via=slack thread=1784577731.070209" in s.format_emit(erow2, 1, 0),
      s.format_emit(erow2, 1, 0))
check("missed is reported", "missed=3" in s.format_emit(erow, 1, 3))
check("replay is a flag, not a new sentinel",
      s.format_emit(erow, 1, 0, replay=True).startswith("SCHED due ")
      and "replay=1" in s.format_emit(erow, 1, 0, replay=True))
check("the line is exactly one line", "\n" not in s.format_emit(erow, 1, 0))

# TEETH - a truncated task id or channel id is worse than useless, it is actively
# wrong. Only the instruction may be cut, and it degrades into a pointer, not a lie.
big = dict(erow, instruction="x" * 5000)
bl = s.format_emit(big, 99)
check("TEETH: truncation cuts the instruction, never the id or the origin",
      "[tsk_x]" in bl and "origin=C123(#ops)" in bl and "run=99" in bl and len(bl) <= s.MAX_LINE_CHARS,
      f"len={len(bl)}")
check("a truncated instruction says where the full text is",
      "sched.py show tsk_x" in bl, bl[-80:])


# === 9. Replay of lost wake-ups =============================================
print("\n--- 9. replay of lost wake-ups ---")

now = time.time()
add_task(ALWAYS, "tsk_lost", min_interval=0.0)
conn.execute("INSERT INTO runs(task_id, fired_at, missed, emitted_line) VALUES (?,?,?,?)",
             ("tsk_lost", int(now - 3600), 0, "old line"))
lines = s.replay_lost_wakeups(conn, now)
check("a pending run with no started_at is re-emitted after a restart",
      any("tsk_lost" in ln for ln in lines), str(lines))
check("a replayed line is marked replay=1", any("replay=1" in ln for ln in lines))
conn.execute("INSERT INTO runs(task_id, fired_at, missed, emitted_line) VALUES (?,?,?,?)",
             ("tsk_lost", int(now - 5), 0, "fresh line"))
lines = s.replay_lost_wakeups(conn, now)
check("a run inside replay_grace_secs is NOT replayed (the line may still be in session)",
      not any(str(int(now - 5)) in ln for ln in lines), str(lines))
for _ in range(4):
    s.replay_lost_wakeups(conn, now)
check("a run nobody ever acknowledges stops replaying and becomes 'lost'",
      conn.execute("SELECT COUNT(*) FROM runs WHERE status='lost'").fetchone()[0] >= 1)

conn.execute("UPDATE runs SET status='ok', started_at=? WHERE task_id='tsk_lost'", (int(now),))
check("an acknowledged run is never replayed",
      not any("tsk_lost" in ln for ln in s.replay_lost_wakeups(conn, now + 10)))


# === 10. Config, via subprocess =============================================
print("\n--- 10. config (subprocess: resolution happens at import) ---")

_BASE = json.loads(open(_EXAMPLE_CONFIG).read())


def run_with_cfg(cfg_obj, snippet="", env_extra=None, argv=(), script=None):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cfg.json")
        if cfg_obj is not None:
            with open(p, "w") as f:
                json.dump(cfg_obj, f)
        env = {**os.environ, "SCHED_CONFIG": p}
        for k in ("SCHED_TICK_SECS", "SCHED_DB", "SCHED_EVAL_TIMEOUT_SECS"):
            env.pop(k, None)
        env.update(env_extra or {})
        code = ("import importlib.util,sys\n"
                f"s=importlib.util.spec_from_file_location('m',{script or _SCRIPT!r})\n"
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n" + snippet)
        r = subprocess.run([sys.executable, "-c", code, *argv],
                           capture_output=True, text=True, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()


# ⚠️ Assert the config RESOLVES, not what it resolves TO. Pinning the literal timezone
# couples the suite to one deployment: change defaults.tz for your own site and a correct
# config fails a test that is supposed to prove the loader works.
rc, out, err = run_with_cfg(_BASE, "print(m.DEFAULT_TZ, m.TICK_SECS, m.MAX_ERRORS)")
_parts = out.split()
check("the shipped example config resolves unchanged",
      rc == 0 and len(_parts) == 3 and _parts[0] == _BASE["defaults"]["tz"]
      and _parts[1] == str(float(_BASE["loop"]["tick_secs"]))
      and _parts[2] == str(_BASE["eval"]["max_errors"]),
      f"rc={rc} out={out} err={err[:120]}")

for key in ("owner", "db", "defaults"):
    broken = json.loads(json.dumps(_BASE))
    del broken[key]
    rc, out, err = run_with_cfg(broken)
    check(f"a missing required '{key}' family is fatal and NAMES the key",
          rc != 0 and key in err, f"rc={rc} err={err[:120]}")

rc, out, err = run_with_cfg(None)
check("a missing config file is fatal", rc != 0 and "SCHED-CONFIG" in err, err[:120])

lean = {"owner": {"claude_config_dir": "~/x"}, "db": {"path": "/tmp/x.db"},
        "defaults": {"tz": "UTC"}}
rc, out, err = run_with_cfg(lean, "print(m.TICK_SECS, m.MAX_FIRES_PER_TICK, m.MIN_INTERVAL_SECS)")
check("optional families default when absent", rc == 0 and out == "1.0 5 30.0",
      f"rc={rc} out={out} err={err[:120]}")

rc, out, err = run_with_cfg(_BASE, "print(m.TICK_SECS)", {"SCHED_TICK_SECS": "7"})
check("env outranks config", rc == 0 and out == "7.0", out)

rc, out, err = run_with_cfg(_BASE, "print(m.DB_PATH)", {"SCHED_DB": "/tmp/other.db"})
check("SCHED_DB retargets the database", out == "/tmp/other.db", out)

other = json.loads(json.dumps(_BASE))
other["db"]["path"] = "/tmp/second/tasks.db"
other["owner"]["claude_config_dir"] = "~/.claude-other"
rc, out, err = run_with_cfg(other, "print(m.DB_PATH, m.LOCK_FILE, m.OWNER_CONFIG_DIR)")
check("a second deployment is a config edit only - db, lock and owner move together",
      "/tmp/second/tasks.db /tmp/second/tasks.db.lock ~/.claude-other" == out, out)

rc, out, err = run_with_cfg(_BASE, "print(list(m._strip_comments(m.cfg('requester'))))")
check("_comment keys are stripped from data",
      rc == 0 and "_comment" not in out, out)

# TEETH - a nonzero exit here makes a correctly-refusing Monitor look like a crash, and
# the fleet's shared "arm at session start" rule depends on refusal being quiet.
rc, out, err = run_with_cfg(_BASE, "m.run_daemon()", {"CLAUDE_CONFIG_DIR": "/tmp/not-the-owner"})
check("TEETH: the owner guard exits 0 with SCHED-GUARD, not an error",
      rc == 0 and "SCHED-GUARD" in err, f"rc={rc} err={err[:160]}")

# TEETH - the per-agent shape. This skill ships config.example.json and deliberately NO
# config.json, because one scheduler per agent means there is no single set of real
# values to commit. The whole shape rests on what happens to an agent that never set
# SCHED_CONFIG: it must FAIL LOUDLY on the absent fallback, never quietly resolve the
# example. Resolving the example would arm a daemon whose owner matches nobody and whose
# db.path is a literal placeholder directory - a scheduler that looks armed, is not, and
# says nothing. Nothing else in the suite covers this, because every other case sets
# SCHED_CONFIG.
_env_no_cfg = {k: v for k, v in os.environ.items() if k != "SCHED_CONFIG"}
_r = subprocess.run([sys.executable, _SCRIPT, "doctor"], capture_output=True, text=True,
                    env=_env_no_cfg)
_fallback = os.path.join(os.path.dirname(_SCRIPT), "config.json")
check("TEETH: with no SCHED_CONFIG the fallback is absent and the failure is loud",
      _r.returncode != 0 and "SCHED-CONFIG" in _r.stderr and _fallback in _r.stderr,
      f"rc={_r.returncode} err={_r.stderr[:160]}")
check("TEETH: and it never silently resolves the example instead",
      "config.example.json" not in _r.stderr.replace(_fallback, ""),
      _r.stderr[:160])

# The example must stay unusable-as-shipped. An adopter who copies it without editing
# gets a config that refuses rather than one that runs against a placeholder path - and
# a reviewer can spot an unreplaced placeholder at a glance. Pins claude-skill section 4's
# rule that a placeholder is realistic but obviously fake, for the three required keys.
check("no config.json ships beside sched.py",
      not os.path.exists(_fallback), _fallback)
check("config.example.json ships and parses", os.path.exists(_EXAMPLE_CONFIG) and _BASE)
for _k, _v in (("owner.claude_config_dir", _BASE["owner"]["claude_config_dir"]),
               ("db.path", _BASE["db"]["path"])):
    check(f"the example's {_k} is an obvious placeholder", "<" in _v and ">" in _v, _v)


# === 11. CLI ================================================================
print("\n--- 11. CLI ---")


def run_cli(*argv, cfg_obj=None, env_extra=None):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cfg.json")
        cfg_obj = cfg_obj or json.loads(json.dumps(_BASE))
        cfg_obj["db"]["path"] = os.path.join(d, "tasks.db")
        with open(p, "w") as f:
            json.dump(cfg_obj, f)
        env = {**os.environ, "SCHED_CONFIG": p}
        env.update(env_extra or {})
        r = subprocess.run([sys.executable, _SCRIPT_FT, *argv], capture_output=True,
                           text=True, env=env)
        return r.returncode, r.stdout, r.stderr


dead = "def should_fire(now, state):\n    return {'fire': False, 'state': state}\n"
rc, out, err = run_cli("add", "--title", "x", "--instruction", "y", "--predicate", dead,
                       "--origin", "slack:CEXAMPLE01", "--requester", "Ada", "--reason", "R")
# TEETH - the silent failure. A predicate that never fires is indistinguishable from a
# scheduler with nothing due; nothing will ever report it. This is the only gate.
check("TEETH: add REFUSES a predicate that never fires", rc != 0 and "REFUSED" in out + err,
      (out + err)[:200])

rc, out, err = run_cli("add", "--title", "x", "--instruction", "y", "--predicate", ALWAYS,
                       "--origin", "slack:CEXAMPLE01", "--requester", "Ada", "--reason", "R")
check("TEETH: add REFUSES a runaway predicate", rc != 0 and "REFUSED" in out + err,
      (out + err)[:200])

rc, out, err = run_cli("add", "--title", "x", "--instruction", "y", "--predicate", ALWAYS,
                       "--origin", "slack:CEXAMPLE01", "--requester", "Ada", "--reason", "R", "--force")
check("--force overrides the refusal", rc == 0, (out + err)[:200])

rc, out, err = run_cli("add", "--title", "x", "--instruction", "y",
                       "--predicate", "import os" + ok_tail,
                       "--origin", "slack:CEXAMPLE01", "--requester", "Ada", "--reason", "R")
check("add rejects an unsafe predicate cleanly (no traceback)",
      rc != 0 and "Traceback" not in err, err[:160])

rc, out, err = run_cli("add", "--title", "daily", "--instruction", "y",
                       "--predicate", DAILY, "--origin", "slack:CEXAMPLE01", "--requester", "Ada", "--reason", "R")
check("add accepts a well-formed daily task and prints its id",
      rc == 0 and "tsk_" in out, (out + err)[:200])
check("add shows the next fire times so a human can catch a misreading",
      "09:00" in out, out[:300])

rc, out, err = run_cli("simulate", "--predicate", DAILY, "--days", "3", "--step", "600")
check("simulate runs from the CLI", rc == 0 and "fires /" in out, (out + err)[:200])
check("simulate warns about a task that never ends", "never returns done" in out)

rc, out, err = run_cli("simulate", "--predicate", "import os" + ok_tail, "--days", "1")
check("simulate rejects an unsafe predicate cleanly (no traceback)",
      rc != 0 and "Traceback" not in err, err[:160])

rc, out, err = run_cli("list")
check("list on an empty db says so, and does not crash", rc == 0, (out + err)[:160])

rc, out, err = run_cli("doctor")
check("doctor runs and reports armed state", rc == 0 and "armed" in out, (out + err)[:200])
# TEETH - a CLI verb printing the daemon's sentinel would inject a phantom wake-up into
# the session of whoever ran it.
# TEETH - `--help` must not be swallowed by the "leading dash means daemon" branch,
# which would arm a tick loop instead of printing help. The one reader who types it is the one a
# flag has just refused, and what they get back must not be a running daemon.
rc, out, err = run_cli("--help")
check("TEETH: --help prints the CLI help and does NOT arm the daemon",
      rc == 0 and "set-meta" in out and "SCHED due" not in out and "SCHED-GUARD" not in out + err,
      (out + err)[:200])
rc, out, err = run_cli("add", "--help")
check("--help on a verb reaches argparse too", rc == 0 and "--reason" in out, out[:200])

check("TEETH: no CLI verb prints a line starting with the daemon's sentinel",
      not any(ln.startswith("SCHED due") for ln in out.splitlines()), out[:200])


# === 12. Loop ===============================================================
print("\n--- 12. loop ---")

rc, out, err = run_with_cfg(_BASE, "m.run_daemon(once=True)",
                            {"CLAUDE_CONFIG_DIR":
                                 os.path.expanduser(_BASE["owner"]["claude_config_dir"]),
                             "SCHED_DB": os.path.join(_tmp.name, "once.db")})
check("--once runs a single tick and exits 0", rc == 0, f"rc={rc} err={err[:160]}")
check("--once skips the lock (it can run alongside a live daemon)",
      not os.path.exists(os.path.join(_tmp.name, "once.db.lock"))
      or "SCHED-GUARD" not in err, err[:160])

# TEETH - the surplus must be DEFERRED, not dropped: nothing is written, so the next
# tick recomputes the identical decision. Purity is what makes that safe.
saved = s.MAX_FIRES_PER_TICK
s.MAX_FIRES_PER_TICK = 1
for i in range(3):
    add_task(ALWAYS, f"tsk_burst{i}", min_interval=0.0)
lines1 = s.run_tick(conn, 9000.0)
lines2 = s.run_tick(conn, 9001.0)
s.MAX_FIRES_PER_TICK = saved
check("max_fires_per_tick caps emissions per tick", len(lines1) == 1, str(lines1))
check("TEETH: the deferred tasks fire on the NEXT tick, they are not dropped",
      len(lines2) == 1 and lines1[0].split()[2] != lines2[0].split()[2],
      f"{lines1} then {lines2}")
check("under the cap, the longest-waiting task wins (no starvation)",
      "tsk_burst" in lines2[0], lines2[0][:80])

check("auto_archive moves old terminal tasks out of the live view",
      (lambda: (conn.execute("UPDATE tasks SET status='done', finished_at=? WHERE id='tsk_cap'",
                             (int(time.time()) - 999 * 86400,)),
                s.auto_archive(conn, time.time()),
                conn.execute("SELECT status FROM tasks WHERE id='tsk_cap'").fetchone()[0])[2]
       == "archived")())

# ---------------------------------------------------------------------------
# BOOT_TIME / uptime() - the fresh-boot guard for self-destructive tasks.
# A reboot task whose 05:00 slot was missed fires on the next boot and, unguarded,
# reboots a host that has been up for 90 seconds - a loop with no self-limit,
# because the reboot kills the session before run-result can be written.
# ---------------------------------------------------------------------------

# TEETH: 0.0 is NOT an acceptable answer on a supported host. 0.0 is "infinite
# uptime", which turns every uptime guard off without a word; accepting it here is how
# a /proc-only reader shipped to macOS with every guard disabled and this suite green.
check("host_boot_time returns a plausible epoch on this host and is cached",
      s.host_boot_time() > 1_500_000_000 and s.host_boot_time() is s.host_boot_time(),
      f"host_boot_time()={s.host_boot_time()!r} on {sys.platform}")

# kern.boottime as macOS prints it. The usec field also contains "sec = ": a parser
# that matched it would read microseconds as the boot time.
_KB = "{ sec = 1790640234, usec = 174452 } Fri Oct  3 10:03:54 2026\n"
check("parse_kern_boottime reads sec, not usec",
      s.parse_kern_boottime(_KB) == 1790640234.0, repr(s.parse_kern_boottime(_KB)))
check("parse_kern_boottime: no sec field is 0.0, not a guess",
      s.parse_kern_boottime("") == 0.0 and s.parse_kern_boottime("usec = 5") == 0.0)


def _boot_time_with(proc_stat, sysctl):
    """host_boot_time() read from fixture sources, cache and seams restored after."""
    saved = (s.PROC_STAT, s.SYSCTL, list(s._BOOT_TIME_CACHE))
    s.PROC_STAT, s.SYSCTL = proc_stat, sysctl
    s._BOOT_TIME_CACHE.clear()
    try:
        return s.host_boot_time()
    finally:
        s.PROC_STAT, s.SYSCTL = saved[0], saved[1]
        s._BOOT_TIME_CACHE[:] = saved[2]


_bt_tmp = tempfile.mkdtemp(prefix="sched-boottime-")
_fake_sysctl = os.path.join(_bt_tmp, "sysctl")
with open(_fake_sysctl, "w") as _fh:
    _fh.write("#!/bin/sh\n[ \"$1 $2\" = \"-n kern.boottime\" ] || exit 1\n"
              f"printf '%s' '{_KB.strip()}'\n")
os.chmod(_fake_sysctl, 0o755)
_fake_stat = os.path.join(_bt_tmp, "stat")
with open(_fake_stat, "w") as _fh:
    _fh.write("cpu  1 2 3\nbtime 1786000000\nprocesses 9\n")
_missing = os.path.join(_bt_tmp, "absent")
check("TEETH: with no /proc/stat (macOS) the boot time comes from kern.boottime",
      _boot_time_with(_missing, _fake_sysctl) == 1790640234.0,
      repr(_boot_time_with(_missing, _fake_sysctl)))
check("/proc/stat btime wins when present (Linux): sysctl is not consulted",
      _boot_time_with(_fake_stat, _fake_sysctl) == 1786000000.0)
check("neither source: 0.0 (infinite uptime, guards off), never an exception",
      _boot_time_with(_missing, _missing) == 0.0)
shutil.rmtree(_bt_tmp)

_g = s.safe_globals("Europe/Berlin", 0.0)
check("boot_time=0 means infinite uptime, so a guard never suppresses in simulation",
      _g["uptime"](1786628000.0) == float("inf"))
_g2 = s.safe_globals("Europe/Berlin", 1786628000.0)
check("uptime(now) is now - BOOT_TIME",
      _g2["uptime"](1786628600.0) == 600.0 and _g2["BOOT_TIME"] == 1786628000.0)

REBOOT_SRC = """
HOURS = (5,)
ARM_LOOKBACK = 8 * 86400
FRESH_BOOT = 3600

def skip_day(d):
    return False

def should_fire(now, state):
    last = state.get("last_due", 0)
    if not last:
        prev = due_slots(now - ARM_LOOKBACK, now, HOURS, TZ, skip=skip_day)
        return {"fire": False, "state": {"last_due": prev[-1] if prev else now}}
    slots = due_slots(last, now, HOURS, TZ, skip=skip_day)
    if not slots:
        return {"fire": False, "state": state}
    if uptime(now) < FRESH_BOOT:
        return {"fire": False, "state": {"last_due": slots[-1]},
                "note": "slot consumed: host booted within the last hour"}
    return {"fire": True, "missed": len(slots) - 1,
            "state": {"last_due": slots[-1]}, "note": "nightly reboot"}
"""
check("the guarded reboot predicate passes the AST allow-list",
      (lambda: (s.validate_predicate(REBOOT_SRC), True)[1])())

# 05:00 CEST slots. 2026-08-11 05:00 CEST = 1786417200; +86400/day.
_missed_state = {"last_due": 1786417200.0}          # last serviced 11 Aug 05:00
_now = 1786628000.0                                 # 13 Aug ~15:33 CEST, 2 slots owed
_row = {"predicate_sha": s.sha_of(REBOOT_SRC), "predicate_src": REBOOT_SRC,
        "tz": "Europe/Berlin", "state_json": __import__("json").dumps(_missed_state)}

_fresh = s.evaluate(_row, _now, boot_time=_now - 90)      # booted 90s ago
check("TEETH: fresh boot suppresses the catch-up fire - no reboot loop",
      _fresh.fire is False, f"fire={_fresh.fire}")
check("TEETH: and the slot is CONSUMED, not left to re-fire an hour later",
      _fresh.state.get("last_due") > _missed_state["last_due"],
      f"{_missed_state['last_due']} -> {_fresh.state.get('last_due')}")

_old = s.evaluate(_row, _now, boot_time=_now - 200_000)    # up for 2+ days
check("TEETH: a genuinely missed slot on a long-lived host still fires",
      _old.fire is True and _old.missed == 1, f"fire={_old.fire} missed={_old.missed}")

_sim = s.simulate(REBOOT_SRC, "Europe/Berlin",
                  1786417200.0, 1786417200.0 + 7 * 86400, step=300)
check("simulate is unaffected by the guard - boot_time defaults to 0, so 7 days = 7 fires",
      len(_sim["fires"]) == 7 and _sim["error"] is None,
      f'fires={len(_sim["fires"])} err={_sim["error"]}')


# === 13. Requester and reason ===============================================
# Every task row says WHO asked and WHY. Both fields are for a reader who was not in
# the conversation - which, for a schedule that outlives it by months, is everyone.
print("\n--- 13. requester and reason ---")

_m_tmp = tempfile.TemporaryDirectory()
_PRISTINE = open(_SCRIPT).read()


def mutant_script(name, *replacements):
    """A copy of sched.py with each (old, new) applied, written to its own directory.

    ⚠️ EACH ANCHOR MUST MATCH EXACTLY ONCE, and a miss raises rather than returning an
    unmutated copy. A text mutation that silently matches nothing runs the PRISTINE
    subject, so the control passes, the guard above it reports green, and it reports
    green for ever - a control that cannot mutate its subject is strictly worse than no
    control, because it manufactures confidence. Every use below is paired with a
    baseline on the same subject, so "the mutant behaved like the original" is a
    reportable failure and never a quiet pass.
    """
    text = _PRISTINE
    for old, new in replacements:
        if text.count(old) != 1:
            raise AssertionError(f"mutant {name}: anchor matched {text.count(old)}x, "
                                 f"expected 1 - the control no longer mutates anything: "
                                 f"{old[:60]!r}")
        text = text.replace(old, new)
    d = os.path.join(_FT, ".claude", "skills", "m-" + name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "sched.py")
    with open(path, "w") as f:
        f.write(text)
    return path


def load_module(path):
    spec = importlib.util.spec_from_file_location(
        "sched_mutant_" + os.path.basename(os.path.dirname(path)), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cli_at(home, *argv, script=None, cfg_patch=None):
    """Run the CLI against a PERSISTENT config+db under `home`, so add/list/show/set-meta
    compose into one flow. run_cli() above makes a fresh database per call by design;
    this section needs the opposite."""
    os.makedirs(home, exist_ok=True)
    p = os.path.join(home, "cfg.json")
    if not os.path.exists(p) or cfg_patch:
        cfg_obj = json.loads(json.dumps(_BASE))
        cfg_obj["db"]["path"] = os.path.join(home, "tasks.db")
        for k, v in (cfg_patch or {}).items():
            cfg_obj[k] = v
        with open(p, "w") as f:
            json.dump(cfg_obj, f)
    env = {**os.environ, "SCHED_CONFIG": p}
    r = subprocess.run([sys.executable, script or _SCRIPT_FT, *argv],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


ADD_OK = ("add", "--title", "Daily gate check", "--instruction", "check the gate",
          "--predicate", DAILY, "--origin", "slack:CEXAMPLE01")

# --- (a) add REFUSES without a reason -----------------------------------------------
_h = os.path.join(_m_tmp.name, "a")
rc, out, err = cli_at(_h, *ADD_OK, "--requester", "Ada")
_msg = out + err
check("add REFUSES a task with no --reason", rc != 0 and "REFUSED" in _msg, _msg[:160])
# The refusal has to TEACH, because it reaches a caller who is already blocked. Pinning
# the three questions is what stops a later edit trimming it to "--reason is required",
# which is a correct message that produces "Ada asked for it" as the reason.
check("the refusal asks why the task is here at all",
      "what would be worse if it were forgotten" in _msg, _msg[:400])
check("the refusal asks why it was added", "Why was it added" in _msg, _msg[:400])
check("the refusal asks what problem it solves", "What problem does it solve" in _msg,
      _msg[:400])
check("the refusal is raised BEFORE the dry run (no schedule is shown then withdrawn)",
      "dry run" not in _msg, _msg[:200])

# CONTROL: with that one guard removed the identical command is ACCEPTED. Without this
# the check above is also satisfied by argparse refusing for an unrelated reason, by a
# broken predicate, or by any other exit path - i.e. by a scheduler that refuses
# everything.
_m = mutant_script("no_reason_guard",
                   ('    if not (a.reason or "").strip():\n        sys.exit(REASON_REFUSAL)\n',
                    ""))
rc_m, out_m, err_m = cli_at(os.path.join(_m_tmp.name, "a_mut"), *ADD_OK,
                            "--requester", "Ada", script=_m)
check("CONTROL: with the reason guard removed, the same add is ACCEPTED",
      rc_m == 0 and "tsk_" in out_m, f"rc={rc_m} {(out_m + err_m)[:200]}")

# --- (b) add STORES both, and every surface SHOWS them --------------------------------
_h = os.path.join(_m_tmp.name, "b")
REASON = ("the gate reds silently on main and nobody looks until the next native push "
          "pays for the whole streak")
rc, out, err = cli_at(_h, *ADD_OK, "--requester", "Ada", "--reason", REASON)
check("add accepts a task carrying a requester and a reason", rc == 0, (out + err)[:200])
_tid = [w for w in out.split() if w.startswith("tsk_")][0]

rc, out, _ = cli_at(_h, "show", _tid)
check("show prints the requester", "requester   Ada" in out, out[:400])
check("show prints the reason IN FULL, not a preview", REASON in out, out[:400])

rc, out, _ = cli_at(_h, "list")
check("list names the requester in the row", "by=Ada" in out, out[:200])

rc, out, _ = cli_at(_h, "show", _tid, "--json")
_j = json.loads(out)["task"]
check("both fields round-trip through the database",
      _j["requester_uid"] == "Ada" and _j["reason"] == REASON, str(_j)[:200])

# --- (c) the requester is a NAME, and an id that cannot become one is refused ---------
_dir = os.path.join(_m_tmp.name, "roster.json")
with open(_dir, "w") as f:
    json.dump({"known_users": {"UEXAMPLE99": "Ada"}}, f)
_WITH_DIR = {"requester": {"directory_file": _dir, "directory_key": "known_users",
                           "id_pattern": "^U[A-Z0-9]{6,}$"}}

_h = os.path.join(_m_tmp.name, "c1")
rc, out, err = cli_at(_h, *ADD_OK, "--requester", "UEXAMPLE99", "--reason", "r",
                      cfg_patch=_WITH_DIR)
check("a user id is resolved to its display name at add time", rc == 0, (out + err)[:200])
rc, out, _ = cli_at(_h, "list")
check("the row stores the NAME, not the id it arrived as",
      "by=Ada" in out and "UEXAMPLE99" not in out, out[:200])

_h = os.path.join(_m_tmp.name, "c2")
rc, out, err = cli_at(_h, *ADD_OK, "--requester", "UNOTINROSTER", "--reason", "r",
                      cfg_patch=_WITH_DIR)
# TEETH - storing the id would satisfy every constraint and every other check here. The
# failure surfaces months later, as a task whose only record of who wanted it is a
# string nobody can identify, at the moment somebody is deciding whether to cancel it.
check("TEETH: an id-shaped requester the roster cannot resolve is REFUSED",
      rc != 0 and "REFUSED" in out + err, (out + err)[:200])
check("the refusal names both ways out (add it to the roster, or pass the name)",
      "directory_file" in out + err and "display name" in out + err, (out + err)[:300])

_h = os.path.join(_m_tmp.name, "c3")
rc, out, err = cli_at(_h, *ADD_OK, "--requester", "claude cli terminal", "--reason", "r",
                      cfg_patch=_WITH_DIR)
rc2, out2, _ = cli_at(_h, "list")
# 'claude remote client' is the longest value in the vocabulary; if the list column
# ever narrows below it, a vocabulary value starts rendering as a truncated fragment.
check("the list column fits the longest vocabulary value",
      cli_at(os.path.join(_m_tmp.name, "c4"), *ADD_OK, "--requester", "claude remote client",
             "--reason", "r")[0] == 0
      and "by=claude remote client" in cli_at(os.path.join(_m_tmp.name, "c4"), "list")[1])
check("a value that is already human-readable is stored verbatim",
      rc == 0 and "by=claude cli terminal" in out2, (out + err + out2)[:250])

_m = mutant_script("no_id_refusal",
                   ("    if _looks_like_id(value):",
                    "    if False and _looks_like_id(value):"))
_h = os.path.join(_m_tmp.name, "c_mut")
rc_m, out_m, err_m = cli_at(_h, *ADD_OK, "--requester", "UNOTINROSTER", "--reason", "r",
                            script=_m, cfg_patch=_WITH_DIR)
rc2, out2, _ = cli_at(_h, "list", script=_m)
check("CONTROL: with the refusal disabled the unresolvable id is stored raw",
      rc_m == 0 and "by=UNOTINROSTER" in out2, f"rc={rc_m} {(out_m + err_m + out2)[:200]}")

# --- (d) the migration reaches a database created before these fields existed ---------
# The fixture is the OLD schema, built by deleting the new columns from the CURRENT one,
# so it tracks the real table instead of a copy that drifts.
_h = os.path.join(_m_tmp.name, "d")
os.makedirs(_h, exist_ok=True)
_olddb = os.path.join(_h, "tasks.db")
# ⚠️ THE FIXTURE IS BUILT FROM A LITERAL LIST, NOT FROM s.ADDED_COLUMNS, AND THAT IS
# THE WHOLE POINT OF THIS TUPLE. Derived from ADDED_COLUMNS the fixture AGREES WITH ANY
# VALUE OF IT: delete a column from ADDED_COLUMNS and the "pre-change" database silently
# grows that column, so no migration is needed, and every check below stays green while
# the shipped code leaves every existing deployment's database without it - after which
# the first write to that column fails on the live scheduler and nowhere else. Measured:
# with the fixture derived, removing both meta_updated_* entries from ADDED_COLUMNS left
# this suite ALL GREEN. A second, independent statement of the same fact is what breaks
# the circle. Adding a column to ADDED_COLUMNS means adding its name here, in the same
# commit; the check immediately below is what says so.
_ADDED_NAMES = ("reason", "meta_updated_by", "meta_updated_at")
check("ADDED_COLUMNS and this suite's pre-migration fixture name the same columns",
      tuple(c for c, _ in s.ADDED_COLUMNS) == _ADDED_NAMES,
      f"{tuple(c for c, _ in s.ADDED_COLUMNS)} vs {_ADDED_NAMES}")
_oldschema = "\n".join(ln for ln in LEGACY_SCHEMA.splitlines()
                       if not any(ln.strip().startswith(c) for c in _ADDED_NAMES))
check("the pre-change fixture really lacks the new columns",
      all(f"  {c}" not in _oldschema for c, _ in s.ADDED_COLUMNS),
      ", ".join(c for c, _ in s.ADDED_COLUMNS))
_oc = sqlite3.connect(_olddb)
_oc.executescript(_oldschema)
_oc.execute("PRAGMA user_version=1")
_now_fix = int(time.time())
_oc.execute(
    "INSERT INTO tasks(id, title, instruction, predicate_src, predicate_sha, tz, status, "
    "state_json, origin_kind, origin_id, requester_uid, created_at, updated_at, fire_count) "
    "VALUES('tsk_old','Old task','the old instruction',?,?,?,'active','{\"last_due\": 1}',"
    "'slack_channel','C9','UEXAMPLE99',?,?,7)",
    (DAILY, s.sha_of(DAILY), TZ, _now_fix, _now_fix))
_oc.commit()
_oc.close()

rc, out, err = cli_at(_h, "list")
check("a pre-change database still lists after the migration", rc == 0 and "tsk_old" in out,
      (out + err)[:200])
_cols = {r[1] for r in sqlite3.connect(_olddb).execute("PRAGMA table_info(tasks)")}
check("the migration added every ADDED_COLUMNS column",
      all(c in _cols for c, _ in s.ADDED_COLUMNS), str(sorted(_cols)))
rc, out, _ = cli_at(_h, "show", "tsk_old", "--json")
_j = json.loads(out)["task"]
check("the pre-existing row survives the migration untouched",
      _j["instruction"] == "the old instruction" and _j["fire_count"] == 7
      and _j["state_json"] == '{"last_due": 1}', str(_j)[:250])
check("a row that predates the field reads as NULL, not as a fabricated reason",
      _j["reason"] is None, str(_j["reason"]))
rc, out, _ = cli_at(_h, "show", "tsk_old")
check("show says the reason is missing rather than printing nothing at all",
      "reason" in out and "(none" in out, out[:400])
# The version number is deliberately NOT bumped: a bump makes every already-running
# daemon exit on sight of the database it is serving.
check("an additive migration does not bump user_version",
      sqlite3.connect(_olddb).execute("PRAGMA user_version").fetchone()[0]
      == s.SCHEMA_VERSION,
      str(sqlite3.connect(_olddb).execute("PRAGMA user_version").fetchone()[0]))

_m = mutant_script(
    "no_ensure_columns",
    ('    have = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}\n',
     "    return\n    have = set()\n"))
_h2 = os.path.join(_m_tmp.name, "d_mut")
os.makedirs(_h2, exist_ok=True)
shutil.copy(_olddb, os.path.join(_h2, "tasks.db"))
sqlite3.connect(os.path.join(_h2, "tasks.db")).executescript(
    "\n".join(f"ALTER TABLE tasks DROP COLUMN {c};" for c in _ADDED_NAMES))
rc_m, out_m, err_m = cli_at(_h2, *ADD_OK, "--requester", "Ada", "--reason", "r", script=_m)
check("CONTROL: without _ensure_columns the same database rejects the write",
      rc_m != 0 and "no column named reason" in (out_m + err_m),
      f"rc={rc_m} {(out_m + err_m)[-200:]}")

# --- (e) the wake-up line carries the reason, and carries it FIRST -------------------
_erow = {"id": "tsk_w", "title": "Daily gate check", "instruction": "check the gate",
         "origin_kind": "slack_dm", "origin_id": "D1", "origin_thread": None,
         "origin_label": None, "requester_uid": "Ada", "reason": REASON}
_line = s.format_emit(_erow, 1, 0)
check("the wake-up line names the requester by name", 'by="Ada"' in _line, _line[:200])
check("the wake-up line carries the reason", REASON in _line, _line[:200])
check("the reason comes BEFORE the instruction on the line",
      _line.index("why:") < _line.index("check the gate"), _line[:200])
check("a task with no reason emits the line unchanged",
      s.format_emit({k: v for k, v in _erow.items() if k != "reason"}, 1, 0).endswith(
          "- check the gate"))

# TEETH - the whole point of the ordering. The payload is what the line budget cuts, and
# it cuts from the end.
_long = dict(_erow, instruction="I" * 5000)
_lline = s.format_emit(_long, 1, 0)
check("TEETH: a 5000-char instruction does not evict the reason",
      REASON in _lline and len(_lline) <= s.MAX_LINE_CHARS, f"len={len(_lline)}")
check("the truncated instruction still points at its own full text",
      "sched.py show tsk_w" in _lline, _lline[-80:])
_bigreason = dict(_erow, reason="R" * 5000)
_bline = s.format_emit(_bigreason, 1, 0)
check("and the reason cannot starve the instruction in return: reason_chars caps it",
      "check the gate" in _bline and len(_bline) <= s.MAX_LINE_CHARS, f"len={len(_bline)}")

# CONTROL: the same formatter with the two payload parts swapped. This is the naive
# ordering, and it passes every check above that uses a SHORT instruction - which is
# exactly why the 5000-char case is the one that matters.
# Two anchors rather than one block, so the swap survives an edit to the comment
# between them - and each still raises if it stops matching.
_SWAP_FROM_A = "\n".join([
    '    payload = []',
    '    reason = collapse(_opt(row, "reason") or "")',
    '',
])
_SWAP_TO_A = "\n".join([
    '    payload = [_fit(collapse(row["instruction"]), budget, pointer)]',
    '    budget -= len(payload[0]) + 3',
    '    reason = collapse(_opt(row, "reason") or "")',
    '',
])
_SWAP_FROM_B = "\n".join([
    '        payload.append(head)',
    '        budget -= len(head) + 3',
    '    payload.append(_fit(collapse(row["instruction"]), budget, pointer))',
    '',
])
_SWAP_TO_B = "        payload.append(head)\n"
_mm = load_module(mutant_script("instruction_first", (_SWAP_FROM_A, _SWAP_TO_A),
                                (_SWAP_FROM_B, _SWAP_TO_B)))
check("CONTROL: instruction-first still passes on a SHORT instruction",
      REASON in _mm.format_emit(_erow, 1, 0), _mm.format_emit(_erow, 1, 0)[:160])
check("CONTROL: instruction-first LOSES the reason on the long one",
      REASON not in _mm.format_emit(_long, 1, 0), _mm.format_emit(_long, 1, 0)[-160:])

# --- (f) set-meta backfills IN PLACE, keeping the fire history -----------------------
# It exists because the alternative - cancel the task and add it back - is what the
# control below measures.
_h = os.path.join(_m_tmp.name, "f")
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "Ada", "--reason", "the first why")
_tid = [w for w in out.split() if w.startswith("tsk_")][0]
_fdb = os.path.join(_h, "tasks.db")
_fc = sqlite3.connect(_fdb)
_fc.execute("UPDATE tasks SET fire_count=9, last_fire_at=?, state_json='{\"last_due\": 5}' "
            "WHERE id=?", (_now_fix, _tid))
_fc.execute("INSERT INTO runs(task_id, fired_at, missed, emitted_line, status) "
            "VALUES(?,?,0,'a line','ok')", (_tid, _now_fix))
_fc.commit()
_fc.close()

rc, out, err = cli_at(_h, "set-meta", _tid, "--requester", "Bea", "--reason", "the new why")
check("set-meta reports what it changed", rc == 0 and "updated" in out, (out + err)[:200])
rc, out, _ = cli_at(_h, "show", _tid, "--json")
_j = json.loads(out)["task"]
_runs = json.loads(out)["runs"]
check("set-meta writes both fields",
      _j["requester_uid"] == "Bea" and _j["reason"] == "the new why", str(_j)[:200])
# TEETH - the reason set-meta exists rather than cancel+add. Each of these is something
# cancel+add destroys: the fire history, the predicate's carried state (so the next slot
# is re-armed from now and a day is silently skipped), and the run log.
check("TEETH: set-meta keeps fire_count, the carried state and the run history",
      _j["fire_count"] == 9 and _j["state_json"] == '{"last_due": 5}' and len(_runs) == 1,
      f'fires={_j["fire_count"]} state={_j["state_json"]} runs={len(_runs)}')
# `sched.py audit` hashes the instruction SEPARATELY from requester+reason, and no verb
# writes the instruction - so a set-meta that moved it would be reported as a write that
# went around sched.py, on the one row a reader is deciding whether to trust.
check("TEETH: set-meta leaves the title and instruction byte-identical",
      _j["title"] == "Daily gate check" and _j["instruction"] == "check the gate",
      f'{_j["title"]!r} {_j["instruction"]!r}')
check("set-meta still refuses an unresolvable id",
      cli_at(_h, "set-meta", _tid, "--requester", "UNOTINROSTER",
             cfg_patch=_WITH_DIR)[0] != 0)
check("set-meta with nothing to set says so instead of bumping rev silently",
      cli_at(_h, "set-meta", _tid)[0] != 0)

# CONTROL: the alternative this verb replaces. cancel+add produces a task with the right
# fields and none of the history - which is why "just cancel and re-add it" is not a fix.
_h = os.path.join(_m_tmp.name, "f_ctl")
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "Ada", "--reason", "the first why")
_tid2 = [w for w in out.split() if w.startswith("tsk_")][0]
_fc = sqlite3.connect(os.path.join(_h, "tasks.db"))
_fc.execute("UPDATE tasks SET fire_count=9 WHERE id=?", (_tid2,))
_fc.commit()
_fc.close()
cli_at(_h, "cancel", _tid2)
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "Bea", "--reason", "the new why")
_tid3 = [w for w in out.split() if w.startswith("tsk_")][0]
rc, out, _ = cli_at(_h, "show", _tid3, "--json")
check("CONTROL: cancel+add gets the fields right and loses the fire history",
      json.loads(out)["task"]["fire_count"] == 0 and _tid3 != _tid2,
      out[:160])

# --- (g) the failure modes a cold review found, each with its own control ------------
# Every check below was written after a peer review reproduced the bug it pins. They
# are grouped because they share one property: each was GREEN under a suite of 168
# checks that looked thorough.

# (g1) set-meta must NOT bump `rev`. The daemon commits a fire with `WHERE id=? AND
# rev=?` on a snapshot it evaluated outside any lock, so a bump landing in that window
# rolls the fire back - no run row, no line, no error. Every other rev-bumping verb also
# stops the task; this is the only one that leaves it running.
_h = os.path.join(_m_tmp.name, "g1")
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "Ada", "--reason", "the first why")
_tid = [w for w in out.split() if w.startswith("tsk_")][0]
_g1db = os.path.join(_h, "tasks.db")
_rev_before = sqlite3.connect(_g1db).execute("SELECT rev FROM tasks WHERE id=?",
                                             (_tid,)).fetchone()[0]
cli_at(_h, "set-meta", _tid, "--reason", "the new why")
_rev_after, _upd = sqlite3.connect(_g1db).execute(
    "SELECT rev, updated_at FROM tasks WHERE id=?", (_tid,)).fetchone()
check("TEETH: set-meta does not bump rev (a bump silently rolls back a racing fire)",
      _rev_after == _rev_before, f"{_rev_before} -> {_rev_after}")
check("set-meta still records that the row changed", _upd > 0, str(_upd))

# The control is the RACE ITSELF, driven in-process against the real daemon path, so
# this is not an argument about rev - it is the dropped fire, measured.
_g1 = os.path.join(_m_tmp.name, "g1_race")
os.makedirs(_g1, exist_ok=True)
_racedb = os.path.join(_g1, "tasks.db")
_saved_db = s.DB_PATH
s.DB_PATH = _racedb
_rc_conn = s.connect(_racedb)
s.migrate(_rc_conn)


def _race_once(bump_rev):
    _rc_conn.execute("DELETE FROM tasks")
    now_i = int(time.time())
    _rc_conn.execute(
        "INSERT INTO tasks(id,title,instruction,predicate_src,predicate_sha,tz,status,"
        "state_json,origin_kind,origin_id,requester_uid,reason,min_interval,created_at,"
        "updated_at) VALUES('tsk_r','T','i',?,?,?,'active','{}','session','-','Ada',"
        "'why',0.0,?,?)", (ALWAYS, s.sha_of(ALWAYS), TZ, now_i, now_i))
    row = _rc_conn.execute("SELECT * FROM tasks WHERE id='tsk_r'").fetchone()
    res = s.evaluate(row, 1000.0)                      # the daemon evaluates its snapshot
    if bump_rev:                                       # ... a CLI write lands here
        _rc_conn.execute("UPDATE tasks SET reason='new', rev=rev+1 WHERE id='tsk_r'")
    else:
        _rc_conn.execute("UPDATE tasks SET reason='new' WHERE id='tsk_r'")
    return s._commit_fire(_rc_conn, row, res, 1000.0)  # ... and the daemon commits


check("CONTROL: a set-meta that DOES bump rev drops the fire it raced",
      _race_once(True) is None
      and _rc_conn.execute("SELECT fire_count FROM tasks WHERE id='tsk_r'").fetchone()[0] == 0)
_line_kept = _race_once(False)
check("TEETH: without the bump the same race emits the line and records the run",
      _line_kept is not None and "tsk_r" in _line_kept
      and _rc_conn.execute("SELECT COUNT(*) FROM runs WHERE task_id='tsk_r'").fetchone()[0] == 1,
      str(_line_kept)[:120])
_rc_conn.close()
s.DB_PATH = _saved_db

# (g2) set-meta must not be a hole through add's refusal.
_h = os.path.join(_m_tmp.name, "g2")
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "Ada", "--reason", "a real why")
_tid = [w for w in out.split() if w.startswith("tsk_")][0]
for _blank in ("", "   "):
    rc, out, err = cli_at(_h, "set-meta", _tid, "--reason", _blank)
    check(f"TEETH: set-meta refuses a blank reason ({_blank!r})",
          rc != 0 and "REFUSED" in out + err, (out + err)[:120])
rc, out, _ = cli_at(_h, "show", _tid, "--json")
check("and the existing reason is still there afterwards",
      json.loads(out)["task"]["reason"] == "a real why", out[:200])

# (g3) the roster is a foreign file; its VALUES are not ours to trust. A Slack user
# OBJECT is the natural shape for a roster entry, and a value with a newline would make
# format_emit return two lines - breaking the one hard output contract this system has.
for _label, _val in (("a dict", {"name": "Ada"}), ("a null", None),
                     ("a number", 7), ("a newline", "Bea\nSmith"),
                     ("whitespace only", "   ")):
    _d2 = os.path.join(_m_tmp.name, f"roster_{_label.replace(' ', '_')}.json")
    with open(_d2, "w") as f:
        json.dump({"known_users": {"UEXAMPLE99": _val}}, f)
    rc, out, err = cli_at(os.path.join(_m_tmp.name, "g3_" + _label.replace(" ", "_")),
                          *ADD_OK, "--requester", "UEXAMPLE99", "--reason", "r",
                          cfg_patch={"requester": {"directory_file": _d2,
                                                   "directory_key": "known_users",
                                                   "id_pattern": "^U[A-Z0-9]{6,}$"}})
    if _label == "a newline":
        # This one is not refused - it is CLEANED, because a name with a stray newline
        # is still a name. What must never happen is that it reaches the emit line.
        check("a roster value with a newline is collapsed, not stored raw",
              rc == 0, (out + err)[:160])
    else:
        check(f"TEETH: a roster value that is {_label} is REFUSED, not stringified",
              rc != 0 and "REFUSED" in out + err, f"rc={rc} {(out + err)[:160]}")

_erow_nl = dict(_erow, requester_uid="Bea\nSmith")
check("TEETH: the emit line is ONE line even if a requester carries a newline",
      "\n" not in s.format_emit(_erow_nl, 1, 0), repr(s.format_emit(_erow_nl, 1, 0))[:160])
check("a requester with spaces is QUOTED, so the prefix stays a field list",
      'by="claude cli terminal"' in s.format_emit(dict(_erow, requester_uid="claude cli terminal"), 1, 0))
check("a comment key in the roster is not a resolvable requester",
      cli_at(os.path.join(_m_tmp.name, "g3_comment"), *ADD_OK, "--requester", "_comment",
             "--reason", "r", cfg_patch=_WITH_DIR)[0] == 0)

# (g4) the emit budget under a prefix long enough to eat it. Every earlier budget check
# runs with a SHORT prefix, which is the regime where the arithmetic cannot break.
_over = []
for _pad in (0, 600, 700, 750, 1000, 2000):
    _r = dict(_erow, origin_kind="slack_channel", origin_id="C1",
              origin_label="#" + "o" * _pad, instruction="I" * 3000, reason="R" * 900)
    _l = s.format_emit(_r, 1, 0)
    _over.append((_pad, len(_l) - s.MAX_LINE_CHARS, "why: R" in _l))
check("TEETH: no prefix length makes the PAYLOAD push the line over max_line_chars",
      all(d <= 0 for _, d, _ in _over), str(_over))
check("and the reason still carries content at every one of them",
      all(has for _, _, has in _over), str(_over))
_saved_rc = s.REASON_CHARS
s.REASON_CHARS = 0
check("TEETH: reason_chars=0 omits the reason segment whole, not as an empty stub",
      "why:" not in s.format_emit(_erow, 1, 0), s.format_emit(_erow, 1, 0)[-120:])
s.REASON_CHARS = _saved_rc

# CONTROL: the cap this pins is `min(REASON_CHARS, budget - 8)`. Removing REASON_CHARS
# from it leaves every check that uses a 1200-char cap and a short instruction GREEN -
# which is why the subject here is the instruction's SURVIVING LENGTH and not merely
# its presence.
_mm2 = load_module(mutant_script(
    "no_reason_cap",
    ("    reason_budget = min(REASON_CHARS, budget - 8)",
     "    reason_budget = budget - 8")))
_bigr = dict(_erow, reason="R" * 5000, instruction="the instruction " * 40)
_kept = lambda ln: ln.count("the instruction")
check("CONTROL: without the reason_chars cap a long reason eats the instruction",
      _kept(_mm2.format_emit(_bigr, 1, 0)) < _kept(s.format_emit(_bigr, 1, 0)) / 2,
      f"mutant kept {_kept(_mm2.format_emit(_bigr, 1, 0))} of the instruction's 40 "
      f"repetitions, the real one kept {_kept(s.format_emit(_bigr, 1, 0))}")
check("and the real one keeps the whole instruction at that size",
      _kept(s.format_emit(_bigr, 1, 0)) == 40, str(_kept(s.format_emit(_bigr, 1, 0))))

# (g5) the migration's check-then-ALTER is racy by construction; losing the race must be
# success, not a traceback. Out of the daemon an unhandled one means it does not START,
# and an unarmed scheduler looks exactly like a day with nothing due.
_h = os.path.join(_m_tmp.name, "g5")
os.makedirs(_h, exist_ok=True)
_racedb2 = os.path.join(_h, "tasks.db")
_c1 = sqlite3.connect(_racedb2)
_c1.executescript(_oldschema)
_c1.execute("PRAGMA user_version=1")
_c1.commit()
_c1.close()
_ca = s.connect(_racedb2)
_cb = s.connect(_racedb2)
_have_a = {r["name"] for r in _ca.execute("PRAGMA table_info(tasks)")}
_have_b = {r["name"] for r in _cb.execute("PRAGMA table_info(tasks)")}
check("both connections observe the column missing (the race window is real)",
      not any(c in _have_a or c in _have_b for c, _ in s.ADDED_COLUMNS))
s._ensure_columns(_ca)
_raced_ok = True
try:
    s._ensure_columns(_cb)                      # the loser: it still sees `have` stale
except Exception as e:                          # noqa: BLE001 - that is the finding
    _raced_ok = False
    _raced_err = e
check("TEETH: losing the ALTER race is success, not an exception",
      _raced_ok, "" if _raced_ok else f"{type(_raced_err).__name__}: {_raced_err}")
check("and the column really is there after the race",
      all(c in {r["name"] for r in _cb.execute("PRAGMA table_info(tasks)")}
          for c, _ in s.ADDED_COLUMNS))
_ca.close()
_cb.close()
# CONTROL: the handler must swallow ONLY the lost race. A blanket `except
# OperationalError: pass` passes every check above and hides a genuinely failed
# migration, after which every write to the new column fails instead.
_notable = s.connect(os.path.join(_h, "notable.db"))
_reraised = False
try:
    s._ensure_columns(_notable)
except sqlite3.OperationalError:
    _reraised = True
_notable.close()
check("TEETH: a real ALTER failure still raises (only the lost race is swallowed)",
      _reraised)

# (g6) claims the earlier checks make but do not measure.
check("--once still runs a single tick after the dispatch change",
      run_cli("--once")[0] == 0, str(run_cli("--once"))[:160])
_h = os.path.join(_m_tmp.name, "g6")
rc, out, _ = cli_at(_h, *ADD_OK, "--requester", "claude remote client", "--reason", "r")
_tid = [w for w in out.split() if w.startswith("tsk_")][0]
rc, out, _ = cli_at(_h, "show", _tid, "--json")
check("a vocabulary value is stored VERBATIM in the row, not merely rendered in a column",
      json.loads(out)["task"]["requester_uid"] == "claude remote client",
      json.loads(out)["task"]["requester_uid"])
# ⚠️ resolve_requester REFUSES by calling sys.exit. That is right for a CLI caller, who
# is present and can fix it; reached from the daemon the same line would take the
# scheduler down, and an unarmed scheduler looks exactly like a day with nothing due.
# Enumerated from the parse tree rather than by slicing the text, because a text slice
# that picks the wrong region reports a clean result either way.
_tree = ast.parse(_PRISTINE)
_callers = {fn.name for fn in ast.walk(_tree) if isinstance(fn, ast.FunctionDef)
            and any(isinstance(c.func, ast.Name) and c.func.id == "resolve_requester"
                    for c in ast.walk(fn) if isinstance(c, ast.Call))}
check("TEETH: resolve_requester is called ONLY from CLI verbs, never the daemon path",
      _callers and all(c.startswith("cmd_") for c in _callers), str(sorted(_callers)))

# (g7) doctor answers "is the roster wired up", which is otherwise indistinguishable
# from "that person is not in the roster" - the refusal text says the same thing for a
# moved file, a renamed key and a genuinely absent person.
_h = os.path.join(_m_tmp.name, "g7")
rc, out, _ = cli_at(_h, "doctor", cfg_patch=_WITH_DIR)
check("doctor reports the requester directory and how many entries it resolved",
      rc == 0 and "requesters" in out and "entries=1" in out, out[:400])
rc, out, _ = cli_at(os.path.join(_m_tmp.name, "g7b"), "doctor",
                    cfg_patch={"requester": {"directory_file": "/nonexistent/roster.json",
                                             "directory_key": "known_users"}})
check("TEETH: doctor says the directory resolves NOTHING rather than reporting it fine",
      "resolves NOTHING" in out, out[:400])


# === 14. The provenance write leaves a trail, and `audit` can see it ==========
# `set-meta` is the one verb built to WRITE provenance, and without meta_updated_by /
# meta_updated_at it is the one write that records nothing: a requester or a reason
# can be replaced and show, list, the wake-up line and any instruction-hash baseline
# all read unchanged.
print("\n--- 14. set-meta's own trail, and the audit verb ---")

AUDIT_ADD = ("add", "--title", "Gate check", "--instruction", "check the gate",
             "--predicate", DAILY, "--origin", "slack:CEXAMPLE01", "--requester", "Ada",
             "--reason", "the gate reds silently and nobody looks")


def _add_one(home, *extra):
    rc, out, err = cli_at(home, *AUDIT_ADD, *extra)
    assert rc == 0, (out + err)[:300]
    return [w for w in out.split() if w.startswith("tsk_")][0]


# --- (a) set-meta stamps who and when ------------------------------------------------
_h = os.path.join(_m_tmp.name, "n1")
_tid = _add_one(_h)
_db = os.path.join(_h, "tasks.db")
_before = sqlite3.connect(_db).execute(
    "SELECT meta_updated_by, meta_updated_at FROM tasks WHERE id=?", (_tid,)).fetchone()
check("a freshly added task has no set-meta stamp (the field is not pre-filled)",
      _before == (None, None), str(_before))

_t0 = int(time.time())
rc, out, err = cli_at(_h, "set-meta", _tid, "--reason", "a rewritten why",
                      "--by", "software-engineer subagent")
_by, _at = sqlite3.connect(_db).execute(
    "SELECT meta_updated_by, meta_updated_at FROM tasks WHERE id=?", (_tid,)).fetchone()
check("set-meta records WHO made the change", rc == 0 and _by == "software-engineer subagent",
      f"rc={rc} by={_by!r} {(out + err)[:160]}")
check("set-meta records WHEN, as a real clock reading", _at is not None and _at >= _t0,
      f"{_at} vs {_t0}")
check("set-meta names the actor in what it prints back",
      "software-engineer subagent" in out, out[:160])
rc, out, _ = cli_at(_h, "show", _tid)
check("show prints the stamp", "meta set" in out and "software-engineer subagent" in out,
      out[:500])
_h1b = os.path.join(_m_tmp.name, "n1b")
rc, out, _ = cli_at(_h1b, "show", _add_one(_h1b))
check("show says (never) rather than omitting the line on a task nobody has edited",
      "meta set" in out and "never" in out, out[:500])

# ⚠️ THE STAMP IS NOT `updated_at`, AND THIS IS THE CHECK THAT SAYS SO. `updated_at` is
# the DAEMON's - _write_state bumps it on every state change - so a `updated_by` paired
# with it would read "Bea, three minutes ago" on a row Bea last touched in March. Drive
# the real daemon path and measure that it moves one timestamp and not the other.
_h = os.path.join(_m_tmp.name, "n2")
os.makedirs(_h, exist_ok=True)
_n2db = os.path.join(_h, "tasks.db")
_saved_db2 = s.DB_PATH
s.DB_PATH = _n2db
_n2 = s.connect(_n2db)
s.migrate(_n2)
_nowi = int(time.time())
_n2.execute(
    "INSERT INTO tasks(id,title,instruction,predicate_src,predicate_sha,tz,status,"
    "state_json,origin_kind,origin_id,requester_uid,reason,meta_updated_by,"
    "meta_updated_at,created_at,updated_at) VALUES('tsk_n2','T','i',?,?,?,'active','{}',"
    "'session','-','Ada','why','Bea',1000,?,1000)",
    (DAILY, s.sha_of(DAILY), TZ, _nowi))
_row_n2 = _n2.execute("SELECT * FROM tasks WHERE id='tsk_n2'").fetchone()
s._write_state(_n2, _row_n2, {"last_due": 1}, time.time())
_ua, _ma, _mb = _n2.execute(
    "SELECT updated_at, meta_updated_at, meta_updated_by FROM tasks WHERE id='tsk_n2'"
).fetchone()
check("TEETH: a daemon state write moves updated_at and leaves the set-meta stamp alone",
      _ua > 1000 and _ma == 1000 and _mb == "Bea", f"updated_at={_ua} meta={_mb}@{_ma}")
_n2.close()
s.DB_PATH = _saved_db2

# --- (b) the migration reaches a database that predates the stamp --------------------
# Section 13(d) already drives the ADDED_COLUMNS mechanism generically; this pins the
# half that is specific to these two - a pre-migration row reads as NEVER STAMPED, not
# as stamped by nobody, and `audit` must not treat that as evidence of anything.
_h = os.path.join(_m_tmp.name, "n3")
os.makedirs(_h, exist_ok=True)
_n3db = os.path.join(_h, "tasks.db")
_c = sqlite3.connect(_n3db)
_c.executescript(_oldschema)
_c.execute("PRAGMA user_version=1")
_c.execute(
    "INSERT INTO tasks(id, title, instruction, predicate_src, predicate_sha, tz, status,"
    " state_json, origin_kind, origin_id, requester_uid, created_at, updated_at) "
    "VALUES('tsk_old2','Old','the old instruction',?,?,?,'active','{}','slack_channel',"
    "'C9','Ada',?,?)", (DAILY, s.sha_of(DAILY), TZ, _nowi, _nowi))
_c.commit()
_c.close()
# `list` first: it is the verb that migrates. `show` does not, so on an unmigrated
# database `show --json` dumps a row that simply has no such key - which is a fact about
# `show`, not about the row, and asserting it here would pin the wrong subject.
cli_at(_h, "list")
rc, out, _ = cli_at(_h, "show", "tsk_old2", "--json")
_j = json.loads(out)["task"]
check("a pre-stamp row reads as never stamped, not as stamped by nobody",
      _j["meta_updated_by"] is None and _j["meta_updated_at"] is None, str(_j)[:200])
# TEETH - the behaviour, not the column list. This is the check that reds if the stamp
# columns are ever dropped from ADDED_COLUMNS: every existing deployment's database is
# a pre-change one, and `set-meta` against it would fail on the live scheduler and in
# no test at all.
rc, out, err = cli_at(_h, "set-meta", "tsk_old2", "--reason", "a why for the old task",
                      "--by", "Alan")
check("TEETH: set-meta works on a database created before the stamp columns existed",
      rc == 0, f"rc={rc} {(out + err)[-200:]}")
rc, out, _ = cli_at(_h, "show", "tsk_old2", "--json")
check("and the stamp it wrote is readable afterwards",
      json.loads(out)["task"]["meta_updated_by"] == "Alan", out[:200])

# --- (c) audit: CHANGED / NEW / GONE, and the round trip ------------------------------
_h = os.path.join(_m_tmp.name, "n4")
_base = os.path.join(_h, "baseline.txt")
_tid = _add_one(_h)
rc, out, err = cli_at(_h, "audit", "--baseline", _base, "--rebaseline")
check("audit --rebaseline writes the baseline", rc == 0 and os.path.exists(_base),
      (out + err)[:200])
rc, out, err = cli_at(_h, "audit", "--baseline", _base)
check("audit round-trips: the set it just baselined reads OK",
      rc == 0 and out.startswith("OK"), f"rc={rc} {(out + err)[:200]}")

rc, out, err = cli_at(_h, "set-meta", _tid, "--reason", "a different why", "--by", "Alan")
rc, out, err = cli_at(_h, "audit", "--baseline", _base)
check("audit flags a REASON change", rc == 1 and out.startswith("CHANGED"),
      f"rc={rc} {(out + err)[:200]}")
# The whole point of §14(a): a difference a set-meta explains and one that went around
# sched.py are the same difference until the stamp separates them.
check("and it names the set-meta that explains it", "set-meta by Alan" in out, out[:250])

cli_at(_h, "audit", "--baseline", _base, "--rebaseline")
cli_at(_h, "set-meta", _tid, "--requester", "Bea", "--by", "Alan")
rc, out, _ = cli_at(_h, "audit", "--baseline", _base)
check("audit flags a REQUESTER change", rc == 1 and "CHANGED" in out, f"rc={rc} {out[:200]}")

# An instruction change cannot be made through any verb - which is the point: the only
# way to produce one is the raw write this audit exists to catch. So it is made raw, and
# the stamp correctly reports that nothing explains it.
cli_at(_h, "audit", "--baseline", _base, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET instruction='do something else entirely', "
           "meta_updated_by=NULL, meta_updated_at=NULL WHERE id=?", (_tid,))
_c.commit(); _c.close()
rc, out, _ = cli_at(_h, "audit", "--baseline", _base)
check("TEETH: audit flags an INSTRUCTION rewritten straight in the database",
      rc == 1 and "CHANGED" in out, f"rc={rc} {out[:200]}")
check("TEETH: and reports that NO VERB could have made it",
      "NO verb writes the instruction" in out, out[:250])

cli_at(_h, "audit", "--baseline", _base, "--rebaseline")
_tid2 = _add_one(_h)
rc, out, _ = cli_at(_h, "audit", "--baseline", _base)
check("audit flags a NEW active task", rc == 1 and out.startswith("NEW") and _tid2 in out,
      f"rc={rc} {out[:200]}")

cli_at(_h, "audit", "--baseline", _base, "--rebaseline")
cli_at(_h, "cancel", _tid2)
rc, out, _ = cli_at(_h, "audit", "--baseline", _base)
check("audit flags a task that is GONE from the active set",
      rc == 1 and "GONE" in out and _tid2 in out, f"rc={rc} {out[:200]}")

# --- (d) the three outcomes are three, and INCONCLUSIVE is never a pass ---------------
# ⚠️ "passed"/"failed" is really worked / genuinely broke / NEVER RAN, and a check that
# collapses the third into the first manufactures the reassuring answer. Every path
# below reached no task at all, so none of them may print OK.
_h = os.path.join(_m_tmp.name, "n5")
_add_one(_h)


def _no_verdict_lines(out):
    """No line of `out` is a CHANGED/NEW/GONE finding.

    A substring test cannot do this job: the INCONCLUSIVE message for a narrowed
    baseline says "every task would read as CHANGED", so `"CHANGED" not in out` fails
    against the very text it is meant to accept. Line-anchored, it asserts what is
    actually at stake - that an audit which never compared anything issues no findings.
    """
    return not any(ln.split(" ")[0] in ("CHANGED", "NEW", "GONE")
                   for ln in out.splitlines())

rc, out, err = cli_at(_h, "audit", "--baseline", os.path.join(_h, "absent.txt"))
check("TEETH: a MISSING baseline is INCONCLUSIVE (rc 2), never OK",
      rc == 2 and "INCONCLUSIVE" in out + err and not out.startswith("OK")
      and _no_verdict_lines(out), f"rc={rc} {out[:200]}")
check("and it names the command that would create one",
      "--rebaseline" in out + err, (out + err)[:250])

_stale = os.path.join(_h, "stale.txt")
with open(_stale, "w") as f:
    f.write("# sha256[:16] of each active task's instruction. Baseline 2026-09-09T20:24Z.\n"
            "tsk_whatever  0123456789abcdef  Some task\n")
rc, out, err = cli_at(_h, "audit", "--baseline", _stale)
check("TEETH: a baseline with no field-set header is INCONCLUSIVE, not a wall of CHANGED",
      rc == 2 and "INCONCLUSIVE" in out + err and _no_verdict_lines(out),
      f"rc={rc} {(out + err)[:250]}")

_narrow = os.path.join(_h, "narrow.txt")
cli_at(_h, "audit", "--baseline", _narrow, "--rebaseline")
_txt = open(_narrow).read().replace("fields=" + "+".join(s.AUDIT_FIELDS),
                                    "fields=instruction")
with open(_narrow, "w") as f:
    f.write(_txt)
rc, out, err = cli_at(_h, "audit", "--baseline", _narrow)
# ⚠️ THE EXPECTATION IS DERIVED HERE, DELIBERATELY, AND THE LITERAL LIVES IN (g). This
# check is about the MESSAGE SHAPE - that the mismatch names the set this build hashes -
# so deriving it keeps it true whatever that set is. What stops that from being vacuous
# is (g)'s literal pin on AUDIT_FIELDS; delete (g) and this site is un-pinned too.
check("TEETH: a baseline covering FEWER fields is INCONCLUSIVE and names both sets",
      rc == 2 and "+".join(s.AUDIT_FIELDS) in out + err
      and "covers instruction;" in out + err and _no_verdict_lines(out),
      f"rc={rc} {(out + err)[:300]}")

_h6 = os.path.join(_m_tmp.name, "n6")
os.makedirs(_h6, exist_ok=True)
_b6 = os.path.join(_h6, "b.txt")
with open(_b6, "w") as f:
    f.write(f"# {s.AUDIT_MARKER}  fields={'+'.join(s.AUDIT_FIELDS)}\n")
rc, out, err = cli_at(_h6, "audit", "--baseline", _b6)
check("TEETH: with no database at all, audit reports it never ran rather than OK",
      rc == 2 and "INCONCLUSIVE" in out + err, f"rc={rc} {(out + err)[:250]}")

# CONTROL: the guard removed. Without it the same missing-header baseline is compared
# anyway and every task reads CHANGED - which is byte-for-byte what a raw-DB write looks
# like, on the one morning a reader most needs the two told apart.
# Built ONCE and reused by (g2) below - the two controls ask the same question of the
# same removal, one about a baseline with no header and one about a baseline with an
# older one.
_m_nofields = mutant_script("no_fieldset_guard",
                            ("    if fields is None:", "    if False:"),
                            ("    if fields != want:", "    if False:"))
rc_m, out_m, err_m = cli_at(_h, "audit", "--baseline", _stale, script=_m_nofields)
check("CONTROL: without the header guard the stale baseline reports CHANGED/GONE instead",
      rc_m == 1 and ("CHANGED" in out_m or "NEW" in out_m or "GONE" in out_m),
      f"rc={rc_m} {(out_m + err_m)[:250]}")

# CONTROL: the stamp. With set-meta's two writes removed, every check in (a) that reads
# the columns fails - but the one that matters is the AUDIT line, which then cannot tell
# a routine backfill from a raw write and says so about neither.
_m = mutant_script(
    "no_meta_stamp",
    ('    sets.append("meta_updated_by=?")\n    params.append(by)\n'
     '    sets.append("meta_updated_at=?")\n    params.append(int(time.time()))\n', ""))
_h7 = os.path.join(_m_tmp.name, "n7")
_tid7 = None
rc, out, err = cli_at(_h7, *AUDIT_ADD, script=_m)
_tid7 = [w for w in out.split() if w.startswith("tsk_")][0]
_b7 = os.path.join(_h7, "b.txt")
cli_at(_h7, "audit", "--baseline", _b7, "--rebaseline", script=_m)
cli_at(_h7, "set-meta", _tid7, "--reason", "a different why", "--by", "Alan", script=_m)
rc_m, out_m, _ = cli_at(_h7, "audit", "--baseline", _b7, script=_m)
check("CONTROL: with the stamp removed, a legitimate set-meta is indistinguishable "
      "from a raw write",
      rc_m == 1 and "stamp UNCHANGED since the baseline" in out_m,
      f"rc={rc_m} {out_m[:250]}")
# BASELINE on the same subject: the real script, same sequence, reports the stamp. Without
# this pair, "the mutant behaved like the original" would pass quietly.
_h8 = os.path.join(_m_tmp.name, "n8")
_tid8 = _add_one(_h8)
_b8 = os.path.join(_h8, "b.txt")
cli_at(_h8, "audit", "--baseline", _b8, "--rebaseline")
cli_at(_h8, "set-meta", _tid8, "--reason", "a different why", "--by", "Alan")
rc, out, _ = cli_at(_h8, "audit", "--baseline", _b8)
check("BASELINE: the real script reports the set-meta on the identical sequence",
      rc == 1 and "set-meta by Alan" in out, out[:250])

# --- (e) the audit hashes the FIELDS, not the trail -----------------------------------
# Hashing meta_updated_* would make every legitimate set-meta a difference, and would
# let a raw write that also cleared the stamp look tidier than one that did not.
_h = os.path.join(_m_tmp.name, "n9")
_tid = _add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET meta_updated_by='someone', meta_updated_at=42 WHERE id=?",
           (_tid,))
_c.commit(); _c.close()
rc, out, _ = cli_at(_h, "audit", "--baseline", _b)
check("the stamp is the trail, not the subject: changing it alone is not a difference",
      rc == 0 and out.startswith("OK"), f"rc={rc} {out[:200]}")

# The ABSORBING pair, and the ordinary pair is not a control. Any two rows that differ
# at all hash differently under a naive join too, so ("a","b","c") vs ("a","","bc")
# passes whatever the serialisation is - measured: with json.dumps swapped for "|".join
# the whole suite stayed ALL CHECKS PASSED on that pair. The pair below is the one that
# separates them: joined on "|" both become "a||b|c", so an editor could move text across
# a field boundary and leave the hash untouched, in the one function whose whole job is
# being unforgeable.
_r1 = {"instruction": "a|", "requester_uid": "b", "reason": "c", "tz": TZ}
_r2 = {"instruction": "a", "requester_uid": "|b", "reason": "c", "tz": TZ}
check("TEETH: text cannot be slid across a field boundary into an identical hash",
      s._audit_hash(_r1, s.AUDIT_FIELDS) != s._audit_hash(_r2, s.AUDIT_FIELDS),
      f"{s._audit_hash(_r1, s.AUDIT_FIELDS)} vs {s._audit_hash(_r2, s.AUDIT_FIELDS)}")
# A join also collapses NULL and the empty string, so a pre-migration row with no reason
# and one whose reason was emptied by a raw write hash alike.
_r3 = {"instruction": "a", "requester_uid": "b", "reason": None, "tz": TZ}
_r4 = {"instruction": "a", "requester_uid": "b", "reason": "", "tz": TZ}
check("TEETH: an absent field and an empty one do not hash alike",
      s._audit_hash(_r3, s.AUDIT_FIELDS) != s._audit_hash(_r4, s.AUDIT_FIELDS),
      f"{s._audit_hash(_r3, s.AUDIT_FIELDS)} vs {s._audit_hash(_r4, s.AUDIT_FIELDS)}")

# CONTROL: the serialisation replaced by the tempting join.
_mm3 = load_module(mutant_script(
    "joined_audit_hash",
    ('        json.dumps([_opt(row, f) for f in fields], ensure_ascii=False).encode()',
     '        "|".join((_opt(row, f) or "") for f in fields).encode()')))
check("CONTROL: joined on a printable separator, the absorbing pair collides",
      _mm3._audit_hash(_r1, _mm3.AUDIT_FIELDS) == _mm3._audit_hash(_r2, _mm3.AUDIT_FIELDS),
      f"{_mm3._audit_hash(_r1, _mm3.AUDIT_FIELDS)} vs "
      f"{_mm3._audit_hash(_r2, _mm3.AUDIT_FIELDS)}")
check("CONTROL: and NULL collapses into the empty string",
      _mm3._audit_hash(_r3, _mm3.AUDIT_FIELDS) == _mm3._audit_hash(_r4, _mm3.AUDIT_FIELDS))

# --- (f) the failure modes a cold review of this section reproduced --------------------

# (f1) A STAMP THAT MERELY EXISTS EXONERATES NOTHING. A row can carry a perfectly
# legitimate set-meta from months ago; printing it beside a difference made this morning
# tells the reader a verb did it, and they stop at that line. So the stamp is compared
# against the BASELINE's, and an instruction difference is never annotated with one at
# all, because no verb writes the instruction.
_h = os.path.join(_m_tmp.name, "n10")
_tid = _add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "set-meta", _tid, "--reason", "an old, legitimate backfill", "--by", "Alan")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET instruction='do something else entirely' WHERE id=?", (_tid,))
_c.commit()
_c.close()
rc, out, _ = cli_at(_h, "audit", "--baseline", _b)
check("TEETH: a raw instruction rewrite on a row carrying an OLD stamp is not explained",
      rc == 1 and "NO verb writes the instruction" in out, f"rc={rc} {out[:300]}")
check("TEETH: and the old stamp is not printed beside it as an explanation",
      "could account for it" not in out, out[:300])

# The same, one layer subtler: the raw write touches requester/reason, where a set-meta
# COULD have done it - but the stamp has not moved since the baseline, so none did.
_h = os.path.join(_m_tmp.name, "n11")
_tid = _add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "set-meta", _tid, "--reason", "an old, legitimate backfill", "--by", "Alan")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET reason='a reason nobody typed' WHERE id=?", (_tid,))
_c.commit()
_c.close()
rc, out, _ = cli_at(_h, "audit", "--baseline", _b)
check("TEETH: a stale stamp reads as UNCHANGED, not as an explanation",
      rc == 1 and "stamp UNCHANGED since the baseline" in out, f"rc={rc} {out[:300]}")

# BASELINE on the same subject: a real set-meta after the baseline DOES read as one.
_h = os.path.join(_m_tmp.name, "n12")
_tid = _add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
cli_at(_h, "set-meta", _tid, "--reason", "a fresh backfill", "--by", "Alan")
rc, out, _ = cli_at(_h, "audit", "--baseline", _b)
check("BASELINE: a set-meta made AFTER the baseline could account for the difference",
      rc == 1 and "set-meta by Alan" in out and "could account for it" in out, out[:300])

# CONTROL: the comparison removed - the stamp is reported whenever one exists. That is
# the naive version, and it passes the BASELINE check above, which is exactly why the two
# stale cases are the ones that matter.
_mm4 = load_module(mutant_script(
    "stamp_not_compared",
    ("    if at is None or str(at) == str(base_stamp):", "    if at is None:")))
_stale_row = {"tz": TZ, "meta_updated_at": 1000, "meta_updated_by": "Alan"}
check("CONTROL: without the baseline comparison a stale stamp reads as an explanation",
      "could account for it" in _mm4._audit_stamp(_stale_row, 1000)
      and "UNCHANGED" in s._audit_stamp(_stale_row, 1000),
      f"{_mm4._audit_stamp(_stale_row, 1000)!r} vs {s._audit_stamp(_stale_row, 1000)!r}")

# (f2) ONE POISONED INTEGER MUST NOT SILENCE THE DETECTOR. meta_updated_at is a column a
# raw writer gains nothing else from touching, and at 99999999999999 datetime raises -
# out of `audit` that kills the whole report, because findings print at the end, and out
# of `show` it aborts before the state, the last error, the predicate and the run history.
_h = os.path.join(_m_tmp.name, "n13")
_tid = _add_one(_h)
_tid_b = _add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET reason='rewritten raw', meta_updated_at=99999999999999 "
           "WHERE id=?", (_tid,))
_c.execute("UPDATE tasks SET reason='also rewritten raw' WHERE id=?", (_tid_b,))
_c.commit()
_c.close()
rc, out, err = cli_at(_h, "audit", "--baseline", _b)
check("TEETH: an unrenderable stamp does not abort the audit", rc == 1,
      f"rc={rc} {(out + err)[-250:]}")
check("TEETH: and the OTHER task's difference is still reported",
      _tid in out and _tid_b in out, out[:400])
rc, out, err = cli_at(_h, "show", _tid)
check("TEETH: show survives an unrenderable stamp and still prints the predicate",
      rc == 0 and "predicate (" in out, f"rc={rc} {(out + err)[-250:]}")

# CONTROL: rendered through the raising formatter, the same row takes the verb down.
_mm5 = mutant_script(
    "raising_ts",
    ('    try:\n        return fmt_local(ts, tz_name)\n'
     '    except (ValueError, OverflowError, OSError, TypeError):\n'
     '        return f"<unrenderable timestamp {ts!r}>"\n',
     "    return fmt_local(ts, tz_name)\n"))
rc_m, out_m, err_m = cli_at(_h, "audit", "--baseline", _b, script=_mm5)
check("CONTROL: without the guard one poisoned row takes the whole audit down",
      "Traceback" in err_m and _tid_b not in out_m, f"rc={rc_m} {(out_m + err_m)[-200:]}")

# (f3) every way of never reaching the tasks is INCONCLUSIVE, not a finding. A traceback
# out of this verb exits 1, which is the code reserved for "a difference was found".
_h = os.path.join(_m_tmp.name, "n14")
_add_one(_h)
_b = os.path.join(_h, "b.txt")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
# A blank or whitespace-only line is TOLERATED - it is formatting, not corruption, and
# refusing it would make an editor's stray newline read as tampering. A line that carries
# tokens but not enough of them is corruption, and the naive `tid, h, *_ = ln.split()`
# raises straight out of the verb as exit 1: the code reserved for "a difference exists".
_bad = os.path.join(_h, "blank.txt")
with open(_bad, "w") as f:
    f.write(open(_b).read() + "   \n\n")
rc, out, err = cli_at(_h, "audit", "--baseline", _bad)
check("a blank line in the baseline is tolerated, not treated as corruption",
      rc == 0 and out.startswith("OK"), f"rc={rc} {(out + err)[-200:]}")
_bad = os.path.join(_h, "bad.txt")
with open(_bad, "w") as f:
    f.write(open(_b).read() + "checked-by-hand\n")
rc, out, err = cli_at(_h, "audit", "--baseline", _bad)
check("TEETH: a malformed baseline line is INCONCLUSIVE, not a finding",
      rc == 2 and "INCONCLUSIVE" in out + err and _no_verdict_lines(out),
      f"rc={rc} {(out + err)[-200:]}")
rc, out, err = cli_at(_h, "audit", "--baseline",
                      os.path.join(_h, "no", "such", "dir", "b.txt"), "--rebaseline")
check("TEETH: a --rebaseline that cannot be written is INCONCLUSIVE, not a finding",
      rc == 2 and "INCONCLUSIVE" in out + err, f"rc={rc} {(out + err)[-200:]}")
_notdb = os.path.join(_m_tmp.name, "n15")
os.makedirs(_notdb, exist_ok=True)
with open(os.path.join(_notdb, "tasks.db"), "w") as f:
    f.write("this is not a database")
rc, out, err = cli_at(_notdb, "audit", "--baseline", _b)
check("TEETH: a file that is not a task database is INCONCLUSIVE, not an empty one",
      rc == 2 and "INCONCLUSIVE" in out + err, f"rc={rc} {(out + err)[-200:]}")

# (f4) the audit must not WRITE the database it is auditing. The verb an operator reaches
# for when they suspect a raw write must not take a write lock, must not create what is
# missing, and must stay usable against a copy or a read-only mount.
_h = os.path.join(_m_tmp.name, "n16")
os.makedirs(_h, exist_ok=True)
_odb = os.path.join(_h, "tasks.db")
_c = sqlite3.connect(_odb)
_c.executescript(_oldschema)
_c.execute("PRAGMA user_version=1")
_c.execute(
    "INSERT INTO tasks(id, title, instruction, predicate_src, predicate_sha, tz, status,"
    " state_json, origin_kind, origin_id, requester_uid, created_at, updated_at) "
    "VALUES('tsk_ro','Old','the old instruction',?,?,?,'active','{}','slack_channel',"
    "'C9','Ada',?,?)", (DAILY, s.sha_of(DAILY), TZ, _nowi, _nowi))
_c.commit()
_c.close()
_b = os.path.join(_h, "b.txt")
rc, out, err = cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
_cols_after = {r[1] for r in sqlite3.connect(_odb).execute("PRAGMA table_info(tasks)")}
check("audit reads an unmigrated database without failing", rc == 0, (out + err)[:200])
check("TEETH: and WITHOUT migrating it - the tamper verb takes no write lock",
      not any(c in _cols_after for c in ("meta_updated_by", "meta_updated_at")),
      str(sorted(_cols_after)))
_missing = os.path.join(_m_tmp.name, "n17")
os.makedirs(_missing, exist_ok=True)
rc, out, err = cli_at(_missing, "audit", "--baseline", _b)
check("TEETH: and it does not CREATE the database it was asked to audit",
      rc == 2 and not os.path.exists(os.path.join(_missing, "tasks.db")),
      f"rc={rc} {(out + err)[:200]}")

# (f5) --rebaseline refuses to take over a baseline another tool owns. That tool has no
# fields= guard on its side, so overwriting its file leaves IT reading every task as
# changed - the failure this verb's header prevents, inflicted on a reader who is not
# even running this verb.
_h = os.path.join(_m_tmp.name, "n18")
_add_one(_h)
_foreign = os.path.join(_h, "foreign.txt")
with open(_foreign, "w") as f:
    f.write("# sha256[:16] of each active task's instruction. Baseline 2026-09-09T20:24Z.\n"
            "tsk_whatever  0123456789abcdef  Some task\n")
_kept = open(_foreign).read()
rc, out, err = cli_at(_h, "audit", "--baseline", _foreign, "--rebaseline")
check("TEETH: --rebaseline refuses a baseline written by another tool",
      rc == 2 and open(_foreign).read() == _kept, f"rc={rc} {(out + err)[:250]}")
rc, out, err = cli_at(_h, "audit", "--baseline", _foreign, "--rebaseline", "--force")
check("and --force takes it over deliberately",
      rc == 0 and s.AUDIT_MARKER in open(_foreign).read(), f"rc={rc} {(out + err)[:200]}")

# --- (g) the audit covers the WHEN as well as the WHAT ---------------------------------
# ⚠️ WHY THIS SUBSECTION EXISTS, AND WHAT BREAKS IF SOMEBODY DELETES IT. A task has two
# halves: the instruction (WHAT the agent does) and the predicate (WHEN it does it,
# carried as predicate_src plus the predicate_sha the code cache is keyed on). A raw
# write to either predicate column changes what the scheduler DOES while leaving every
# word an operator reads - title, instruction, requester, reason - byte-identical, and
# both of its outcomes are silent in production: a dead schedule is indistinguishable
# from a quiet one, and a runaway one floods a session. Drop the predicate columns from
# AUDIT_NO_VERB_FIELDS and NOTHING here goes red without these checks: the verb keeps
# printing OK, for ever, over a rewritten predicate.

# ⚠️ THE TWO PINS COME FIRST SO A REGROUPING NAMES ITSELF. Everything below builds
# mutants anchored on the literal tuples, and mutant_script RAISES when an anchor stops
# matching - correct, but a traceback is a harness fault, and a harness fault pronounces
# on nothing. Run first, these print one [FAIL] saying exactly what the build now has,
# and the traceback that follows is the second signal rather than the only one.
# ⚠️ AND THE SPLIT IS PINNED SEPARATELY FROM THE UNION, BECAUSE THE SPLIT IS THE
# LOAD-BEARING HALF. AUDIT_FIELDS is the concatenation, so moving predicate_src into
# AUDIT_META_FIELDS leaves the union pin satisfied while the verb starts offering a
# `set-meta` stamp as the explanation for a rewritten predicate - the one sentence
# cmd_audit's own comment says it must never print.
# Deriving either expectation from the constants instead would agree with any value of
# them, including one that quietly dropped a predicate column - the exact regression this
# subsection exists to catch, passing in silence. The ORDER is pinned too: the baseline
# header is compared as a string, so a reordered tuple makes every baseline on disk
# INCONCLUSIVE for no reason a reader can act on.
check("AUDIT_FIELDS is the five audited fields, in this order",
      s.AUDIT_FIELDS == ("instruction", "predicate_src", "predicate_sha",
                         "requester_uid", "reason"), str(s.AUDIT_FIELDS))
check("and the predicate columns are in the NO-VERB group, not the stamp-explainable one",
      s.AUDIT_NO_VERB_FIELDS == ("instruction", "predicate_src", "predicate_sha")
      and s.AUDIT_META_FIELDS == ("requester_uid", "reason"),
      f"{s.AUDIT_NO_VERB_FIELDS} / {s.AUDIT_META_FIELDS}")

# The mutant is the PREVIOUS build: the audit that covered neither predicate column. It
# serves twice - as the control for (g1), and as the honest way to produce a baseline
# from that build for (g2).
_m_pred = mutant_script(
    "audit_without_predicate",
    ('AUDIT_NO_VERB_FIELDS = ("instruction", "predicate_src", "predicate_sha")',
     'AUDIT_NO_VERB_FIELDS = ("instruction",)'))

# (g1) ONE RAW WRITE, TWO BASELINES TAKEN BEFORE IT, AND THAT ORDER IS THE WHOLE CONTROL.
# ⚠️ Taking the old build's baseline AFTER the write bakes the write into it, so any
# contamination of that write - an instruction rewritten in the same UPDATE, a fixture
# whose .replace() silently matched nothing - is invisible to BOTH sides and the pair
# passes while measuring the coverage that was already there. Measured: with `_b_old`
# taken afterwards, an UPDATE that also rewrote the instruction left every check in this
# block green, control included. Both baselines are taken first; then ONE write moves the
# predicate and nothing else; then the two builds are asked about the SAME database.
_h = os.path.join(_m_tmp.name, "n19")
_tid = _add_one(_h)
_b = os.path.join(_h, "b.txt")
_b_old = os.path.join(_h, "b_old.txt")
cli_at(_h, "audit", "--baseline", _b, "--rebaseline")
cli_at(_h, "audit", "--baseline", _b_old, "--rebaseline", script=_m_pred)
# A predicate that never fires: HOURS emptied, so due_slots yields nothing for ever. This
# is the write the whole subsection is about - the task still says it checks the gate
# daily, and it never checks it again. predicate_sha is left alone deliberately: that is
# what a hand-editor does, and it is the state in which a long-lived daemon keeps running
# the previously compiled object.
_dead = DAILY.replace("HOURS = (9,)", "HOURS = ()")
assert _dead != DAILY, "the fixture's anchor stopped matching - the write is a no-op"
_c = sqlite3.connect(os.path.join(_h, "tasks.db"))
_c.execute("UPDATE tasks SET predicate_src=? WHERE id=?", (_dead, _tid))
_c.commit()
_c.close()
rc, out, _ = cli_at(_h, "audit", "--baseline", _b)
check("TEETH: audit flags a PREDICATE rewritten straight in the database",
      rc == 1 and "CHANGED" in out and _tid in out, f"rc={rc} {out[:300]}")
check("TEETH: and reports that NO VERB could have made it",
      "NO verb writes the instruction or the predicate" in out, out[:300])
# A reader holding a rewritten PREDICATE who is told only "instruction" opens an
# instruction that is byte-identical and concludes the verb is broken.
check("the finding names the predicate, not the instruction alone",
      "instruction/predicate" in out, out[:300])
check("and no stamp is offered as an explanation for it",
      "could account for it" not in out, out[:300])

# CONTROL and BASELINE in one: the previous build, asked about the SAME database and the
# SAME write, reports OK. That is what the coverage was, and - because its baseline was
# taken before the write - it also proves the write moved the predicate and nothing else:
# had the instruction, requester or reason drifted, the narrower audit would have caught
# it too.
rc_m, out_m, err_m = cli_at(_h, "audit", "--baseline", _b_old, script=_m_pred)
check("CONTROL: the build without the predicate reads the same rewritten predicate as OK",
      rc_m == 0 and out_m.startswith("OK"), f"rc={rc_m} {(out_m + err_m)[:250]}")

# (g1b) THE SHA ALONE IS A FINDING, AND IT IS NOT A REDUNDANT COPY OF THE SOURCE.
# _CODE_CACHE is keyed on predicate_sha (load_code), so in a long-lived daemon that column
# decides which compiled object RUNS. Rewriting the sha alone - to one already cached in
# that process from another task - runs that other task's predicate while predicate_src
# still reads honest: WHEN this task fires changes, and a source-only audit sees nothing.
_h19b = os.path.join(_m_tmp.name, "n19b")
_tid19b = _add_one(_h19b)
_b19b = os.path.join(_h19b, "b.txt")
cli_at(_h19b, "audit", "--baseline", _b19b, "--rebaseline")
_c = sqlite3.connect(os.path.join(_h19b, "tasks.db"))
_c.execute("UPDATE tasks SET predicate_sha=? WHERE id=?", (s.sha_of(_dead), _tid19b))
_c.commit()
_c.close()
rc, out, _ = cli_at(_h19b, "audit", "--baseline", _b19b)
check("TEETH: a predicate_sha rewritten alone, with the source untouched, is a finding",
      rc == 1 and "CHANGED" in out and "NO verb writes" in out, f"rc={rc} {out[:300]}")

# (g2) A BASELINE FROM BEFORE THE WIDENING IS INCONCLUSIVE WITH A MIGRATION HINT - never a
# page of CHANGED, and never a smaller clean. Both wrong answers are worse than no answer:
# a page of CHANGED is byte-for-byte what the tampering this verb looks for produces, and
# an OK over three of five fields is a reader told to stop looking at the fields that moved.
_h20 = os.path.join(_m_tmp.name, "n20")
_tid20 = _add_one(_h20)
_b20 = os.path.join(_h20, "b_old_build.txt")
cli_at(_h20, "audit", "--baseline", _b20, "--rebaseline", script=_m_pred)
check("the old build's baseline really does declare the narrower set",
      "fields=instruction+requester_uid+reason" in open(_b20).read(),
      open(_b20).read()[:200])
rc, out, err = cli_at(_h20, "audit", "--baseline", _b20)
check("TEETH: a baseline from before the widening is INCONCLUSIVE, not a verdict",
      rc == 2 and "INCONCLUSIVE" in out + err and not out.startswith("OK")
      and _no_verdict_lines(out), f"rc={rc} {(out + err)[:300]}")
check("and it names both field sets, so the reader can see WHICH widened",
      "covers instruction+requester_uid+reason" in out + err
      and "instruction+predicate_src+predicate_sha+requester_uid+reason" in out + err,
      (out + err)[:400])
check("and it names the one-time command that migrates the baseline",
      "--rebaseline" in out + err and _b20 in out + err, (out + err)[:400])

# ⚠️ AND THE COMMAND IT NAMES HAS TO WORK, WITH NOTHING ADDED - AGAINST A FILE THIS BUILD
# HAS NEVER SEEN. The hint reaches a reader who is already blocked and about to type it.
# The fixture is written by hand rather than by the mutant, so it pins the MARKER LITERAL
# an operator's file carries: bump AUDIT_MARKER while widening the field set and this
# file becomes FOREIGN, the mismatch message degrades to the weaker "carries no header"
# form that never names the two field sets, and the --rebaseline the hint prints is then
# refused as a takeover - exit 2 at exactly that reader. The takeover refusal is real and
# right for a file some OTHER tool wrote; the two cases share a verb and must not share
# an answer.
_h20b = os.path.join(_m_tmp.name, "n20b")
_tid20b = _add_one(_h20b)
_b20b = os.path.join(_h20b, "operator_baseline.txt")
with open(_b20b, "w") as f:
    f.write("# sched.py audit baseline v1  fields=instruction+requester_uid+reason  "
            "taken 2026-09-09T21:10Z\n"
            "# <task id>  <instruction hash>  <requester+reason hash>  "
            "<meta_updated_at>  <title>.\n"
            f"{_tid20b}  0123456789abcdef  fedcba9876543210  -  Gate check\n")
rc, out, err = cli_at(_h20b, "audit", "--baseline", _b20b)
check("TEETH: a hand-held operator baseline on the old marker is INCONCLUSIVE, not foreign",
      rc == 2 and "covers instruction+requester_uid+reason" in out + err
      and "NOT written by this verb" not in out + err, f"rc={rc} {(out + err)[:300]}")
rc, out, err = cli_at(_h20b, "audit", "--baseline", _b20b, "--rebaseline")
check("TEETH: the migration hint's command retakes it with no --force",
      rc == 0 and "fields=instruction+predicate_src+predicate_sha+requester_uid+reason"
      in open(_b20b).read(), f"rc={rc} {(out + err)[:250]}")
rc, out, _ = cli_at(_h20b, "audit", "--baseline", _b20b)
check("and the retaken baseline reads clean, so the migration is one command and done",
      rc == 0 and out.startswith("OK"), f"rc={rc} {out[:200]}")

# CONTROL: the header guard removed. The old baseline is then compared anyway and every
# task reads CHANGED - which is what an operator would have been handed on the morning
# after this widening, with no way to tell it from a raw write.
rc_m, out_m, err_m = cli_at(_h20, "audit", "--baseline", _b20, script=_m_nofields)
check("CONTROL: without the header guard the pre-widening baseline reports CHANGED",
      rc_m == 1 and any(ln.startswith("CHANGED") for ln in out_m.splitlines()),
      f"rc={rc_m} {(out_m + err_m)[:250]}")

# ⚠️ AND THE HEADER CANNOT BE APPENDED PAST THE ROWS. Read the LAST marker line and one
# appended comment line declares a field set the hashes below it were never taken under -
# which disables the guard above from outside the tool, on a file that is mode 0644 in an
# agent's own state directory. The relabelled file then prints a full page of CHANGED
# carrying the "written around sched.py" accusation, i.e. the guard fails in the exact
# direction it exists to prevent.
_b20c = _b20 + ".appended"
with open(_b20c, "w") as f:
    f.write(open(_b20).read()
            + f"# {s.AUDIT_MARKER}  fields={'+'.join(s.AUDIT_FIELDS)}\n")
rc, out, err = cli_at(_h20, "audit", "--baseline", _b20c)
check("TEETH: a second header appended past the rows is malformed, not a relabelling",
      rc == 2 and "INCONCLUSIVE" in out + err and _no_verdict_lines(out),
      f"rc={rc} {(out + err)[:300]}")

# (g3) THE ROUND TRIP. The field set itself is pinned at the top of this subsection.
_h21 = os.path.join(_m_tmp.name, "n21")
_tid21 = _add_one(_h21)
_b21 = os.path.join(_h21, "b.txt")
rc, out, err = cli_at(_h21, "audit", "--baseline", _b21, "--rebaseline")
check("rebaseline declares every audited field in its header",
      rc == 0 and "fields=instruction+predicate_src+predicate_sha+requester_uid+reason"
      in open(_b21).read(), f"rc={rc} {(out + err)[:200]}")
rc, out, err = cli_at(_h21, "audit", "--baseline", _b21)
check("and the fresh baseline round-trips clean, naming what it covered",
      rc == 0 and out.startswith("OK")
      and "instruction+predicate_src+predicate_sha+requester_uid+reason" in out,
      f"rc={rc} {(out + err)[:250]}")
# The round trip has to survive a set-meta, or the widening would have made every
# legitimate backfill unexplainable: the predicate columns are hashed in the OTHER group.
cli_at(_h21, "set-meta", _tid21, "--reason", "a fresh backfill", "--by", "Alan")
rc, out, _ = cli_at(_h21, "audit", "--baseline", _b21)
check("a set-meta after the widening is still reported as a set-meta, not as a rewrite",
      rc == 1 and "set-meta by Alan" in out
      and "NO verb writes" not in out, out[:300])

# === 15. A restart loop re-fires nothing ====================================
# The daemon runs as a systemd unit with Restart=always and a periodic refresh
# restart, so "the process starts again" is routine, not exceptional. What a start
# may do is replay a PENDING run's line (replay=1, bounded, then 'lost'); what it
# must never do is fire the task again, because a fire commits the predicate's new
# state in the same transaction as the run row. Each `--once` below is a whole
# daemon start: fresh process, replay pass, one tick.
print("\n--- 15. a restart loop re-fires nothing ---")

_SLOT = int(time.time()) - 30
ONCE_SRC = f"""
SLOT = {_SLOT}

def should_fire(now, state):
    if now < SLOT or state.get("done_slot") == SLOT:
        return {{"fire": False, "state": state}}
    return {{"fire": True, "state": {{"done_slot": SLOT}}}}
"""
GUARDED_SRC = ONCE_SRC.replace(
    '    return {"fire": True,',
    '    if uptime(now) < 3600:\n'
    '        return {"fire": False, "state": {"done_slot": SLOT}}\n'
    '    return {"fire": True,')
assert GUARDED_SRC != ONCE_SRC
_emit_patch = dict(_BASE.get("emit", {}), replay_grace_secs=0)


def restart_loop(home, src, restarts=4, script=None):
    rc, out, err = cli_at(home, "add", "--title", "slot", "--instruction", "do it",
                          "--predicate", src, "--origin", "slack:CEXAMPLE01", "--requester", "Ada",
                          "--reason", "pins restart semantics", "--min-interval", "0",
                          script=script, cfg_patch={"emit": _emit_patch})
    assert rc == 0, (out + err)[:400]
    tid = [w for w in out.split() if w.startswith("tsk_")][0]
    fires, replays = 0, 0
    for i in range(restarts):
        if i:
            time.sleep(1.05)        # a distinct second per start: (task, fired_at) is unique
        rc, out, err = cli_at(home, "--once", script=script)
        mine = [l for l in out.splitlines() if l.startswith(f"SCHED due [{tid}]")]
        fires += sum(1 for l in mine if "replay=1" not in l)
        replays += sum(1 for l in mine if "replay=1" in l)
    db = sqlite3.connect(os.path.join(home, "tasks.db"))
    runs = db.execute("SELECT status FROM runs WHERE task_id=?", (tid,)).fetchall()
    fc = db.execute("SELECT fire_count FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    return fires, replays, [r[0] for r in runs], fc


_f, _r, _runs, _fc = restart_loop(os.path.join(_m_tmp.name, "r1"), ONCE_SRC)
check("TEETH: four daemon starts fire a once-per-slot task exactly once",
      _f == 1 and _fc == 1 and len(_runs) == 1, f"fires={_f} fire_count={_fc} runs={_runs}")
check("its unacknowledged run is replayed at most MAX_REPLAYS_PER_RUN times, then 'lost'",
      _r <= s.MAX_REPLAYS_PER_RUN and _runs == ["lost"], f"replays={_r} runs={_runs}")

_f, _r, _runs, _fc = restart_loop(os.path.join(_m_tmp.name, "r2"), GUARDED_SRC)
_up = time.time() - s.host_boot_time()
check("an uptime()-guarded task fires at most once across the same restart loop",
      _f <= 1 and _fc == _f and (_f == 1) == (_up >= 3600 + 10),
      f"fires={_f} host uptime={_up:.0f}s")

_b = [run_with_cfg(_BASE, "print(m.host_boot_time())")[1] for _ in range(2)]
# The host's own answer, read here by a separate route: /proc/stat on Linux, the
# kern.boottime text split by hand on macOS (not sched.py's parser).
if os.path.exists("/proc/stat"):
    _btime = next(l.split()[1] for l in open("/proc/stat") if l.startswith("btime "))
else:
    _btime = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True,
                            text=True).stdout.split("{ sec = ", 1)[1].split(",", 1)[0]
check("uptime() counts from host boot, not process start: two processes, one BOOT_TIME",
      _b[0] == _b[1] and float(_b[0]) == float(_btime), f"{_b} vs btime {_btime}")

# CONTROL: the same loop against a scheduler that commits the OLD state with a fire.
# It must re-fire on every start; if it does not, the loop above cannot see a re-fire.
_mut = mutant_script("refire_on_restart", (
    "(json.dumps(res.state), _now_i(now), _now_i(now), fire_count,",
    "(row['state_json'], _now_i(now), _now_i(now), fire_count,"))
_f, _r, _runs, _fc = restart_loop(os.path.join(_m_tmp.name, "r3"), ONCE_SRC, script=_mut)
check("CONTROL: a scheduler that drops the fired state re-fires on every restart",
      _f == 4, f"fires={_f} (the loop cannot see a re-fire if this is 1)")


# === 16. Origins are transport plus kind; a legacy database is never altered =====
# An origin is (transport, kind). A database this version creates stores both; a
# database created before (no origin_transport column - all six live ones) keeps its
# Slack-only vocabulary, is never altered, and refuses every other transport with the
# one message below. Both formats are read by decode_origin() alone.
print("\n--- 16. transport-neutral origins ---")

# Written out here, not read from s.LEGACY_REFUSAL: the message is a contract stated
# in the design, and a test that compared the code with itself would pass any wording.
EXPECTED_LEGACY_REFUSAL = (
    "REFUSED: this scheduler database predates transport-neutral origins and stores "
    "Slack origins only; a {transport} origin needs a database created by this version.")
_T1, _T2, _T3 = "1700000000.000001", "1700000000.000002", "1700000000.000003"


def _legacy_db(home):
    os.makedirs(home, exist_ok=True)
    p = os.path.join(home, "tasks.db")
    c = sqlite3.connect(p)
    c.executescript(LEGACY_SCHEMA)
    c.execute("PRAGMA user_version=1")
    c.commit()
    c.close()
    return p


def _cols(p):
    return {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(tasks)")}


def _add16(home, origin, *extra, script=None, cfg_patch=None, requester="Ada"):
    rc, out, err = cli_at(home, "add", "--title", "o", "--instruction", "i", "--predicate",
                          DAILY, "--origin", origin, "--requester", requester, "--reason",
                          "pins how an origin is stored", *extra, script=script,
                          cfg_patch=cfg_patch)
    tid = next((w for w in out.split() if w.startswith("tsk_")), None)
    return rc, out, err, tid


def _stored(p, tid, cols="origin_kind, origin_id, origin_thread"):
    return sqlite3.connect(p).execute(f"SELECT {cols} FROM tasks WHERE id=?",
                                      (tid,)).fetchone()


def _ntasks(p):
    return sqlite3.connect(p).execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


# --- (a) a LEGACY database: every Slack form lands in the old vocabulary ------------
_hl = os.path.join(_m_tmp.name, "o_legacy")
_ldb = _legacy_db(_hl)
check("CONTROL: the legacy fixture has no origin_transport column to begin with",
      "origin_transport" not in _cols(_ldb) and "origin_kind" in _cols(_ldb),
      str(sorted(_cols(_ldb))))
for _origin, _extra, _want in (
        ("slack:CEXAMPLE01", (), ("slack_channel", "CEXAMPLE01", None)),
        ("dm:DEXAMPLE01", (), ("slack_dm", "DEXAMPLE01", None)),
        ("slack:channel:CEXAMPLE02", (), ("slack_channel", "CEXAMPLE02", None)),
        ("slack:dm:DEXAMPLE02", (), ("slack_dm", "DEXAMPLE02", None)),
        (f"slack:channel:CEXAMPLE03:{_T1}", (), ("slack_thread", "CEXAMPLE03", _T1)),
        ("slack:CEXAMPLE04", ("--thread", _T2), ("slack_thread", "CEXAMPLE04", _T2)),
        ("dm:DEXAMPLE03", ("--thread", _T3), ("slack_dm", "DEXAMPLE03", _T3)),
        ("session", (), ("session", "-", None))):
    rc, out, err, tid = _add16(_hl, _origin, *_extra)
    got = _stored(_ldb, tid) if tid else None
    check(f"legacy database: --origin {_origin} {' '.join(_extra)}".rstrip()
          + f" is stored as {_want[0]}",
          rc == 0 and tuple(got or ()) == _want, f"rc={rc} got={got} {(out + err)[-160:]}")
check("TEETH: after every add the legacy table STILL has no origin_transport column",
      "origin_transport" not in _cols(_ldb), str(sorted(_cols(_ldb))))
check("and the legacy database is still user_version 1",
      sqlite3.connect(_ldb).execute("PRAGMA user_version").fetchone()[0] == 1)

_before = _ntasks(_ldb)
for _t, _origin in (("discord", "discord:channel:123456789012345678"),
                    ("chatx", "chatx:channel:XC123")):
    rc, out, err, tid = _add16(_hl, _origin)
    check(f"legacy database: a {_t} origin exits 2 with the legacy refusal, verbatim",
          rc == 2 and err.strip().splitlines()[-1:] == [
              EXPECTED_LEGACY_REFUSAL.format(transport=_t)],
          f"rc={rc} err={err.strip()[-220:]!r}")
check("and a refused origin writes no row", _ntasks(_ldb) == _before,
      f"{_before} -> {_ntasks(_ldb)}")
rc, out, err, _ = _add16(_hl, "chatx:channel:XC123")
check("the refusal comes before the dry run: no schedule is shown and then withdrawn",
      rc == 2 and "predates transport-neutral origins" in err and "dry run" not in out,
      f"rc={rc} out={out[:120]!r}")

# CONTROL for the column check above: a scheduler whose _ensure_columns added the
# column would alter the live databases - and this is what that looks like. If the
# mutant's database ALSO lacks the column, the check above cannot see the trap.
_m = mutant_script("adds_origin_transport",
                   ('    ("meta_updated_at", "INTEGER"),\n',
                    '    ("meta_updated_at", "INTEGER"),\n    ("origin_transport", "TEXT"),\n'))
_hm = os.path.join(_m_tmp.name, "o_legacy_mut")
_mdb = _legacy_db(_hm)
cli_at(_hm, "list", script=_m)
check("CONTROL: a mutant that lists origin_transport in ADDED_COLUMNS alters the legacy "
      "table", "origin_transport" in _cols(_mdb), str(sorted(_cols(_mdb))))
rc_m, out_m, err_m, _ = _add16(_hm, "slack:CEXAMPLE01", script=_m)
check("CONTROL: ... after which a Slack add on that live table fails at the database",
      rc_m != 0 and "CHECK constraint failed" in out_m + err_m,
      f"rc={rc_m} {(out_m + err_m)[-200:]}")

# --- (b) a FRESH database: transport and kind, both stored -------------------------
_hf = os.path.join(_m_tmp.name, "o_fresh")
_fdb = os.path.join(_hf, "tasks.db")
for _origin, _extra, _want in (
        ("slack:CEXAMPLE01", (), ("channel", "slack", "CEXAMPLE01", None)),
        ("dm:DEXAMPLE01", (), ("dm", "slack", "DEXAMPLE01", None)),
        ("chatx:channel:XC123", (), ("channel", "chatx", "XC123", None)),
        ("chatx:dm:XC124:42", (), ("thread", "chatx", "XC124", "42")),
        ("slack:CEXAMPLE04", ("--thread", _T2), ("thread", "slack", "CEXAMPLE04", _T2)),
        ("session", (), ("session", None, "-", None))):
    rc, out, err, tid = _add16(_hf, _origin, *_extra)
    got = _stored(_fdb, tid, "origin_kind, origin_transport, origin_id, origin_thread") \
        if tid else None
    check(f"fresh database: --origin {_origin} {' '.join(_extra)}".rstrip()
          + f" is stored as {_want[:2]}",
          rc == 0 and tuple(got or ()) == _want, f"rc={rc} got={got} {(out + err)[-160:]}")
check("a fresh database is created with the origin_transport column",
      "origin_transport" in _cols(_fdb), str(sorted(_cols(_fdb))))

_before = _ntasks(_fdb)
for _origin, _needle in (
        ("discord:channel:123456789012345678", "placeholder transport"),
        ("nosuch:channel:C123", "no transport named 'nosuch'"),
        ("slack:channel:bad-id", "not a slack conversation id"),
        ("slack:channel:CEXAMPLE01:not-a-ts", "not a slack message id"),
        ("slack:group:CEXAMPLE01", "is not an origin"),
        ("irc:CEXAMPLE01", "is not an origin"),
        ("slack:", "names no conversation")):
    rc, out, err, tid = _add16(_hf, _origin)
    check(f"fresh database: --origin {_origin} is refused, exit 2 ({_needle})",
          rc == 2 and _needle in err and "Traceback" not in err,
          f"rc={rc} err={err.strip()[-200:]!r}")
check("and no refused origin wrote a row", _ntasks(_fdb) == _before,
      f"{_before} -> {_ntasks(_fdb)}")

# The CHECK is the database's own guarantee, independent of the CLI. The accepted
# insert first, so each refusal below is the CHECK speaking and not another constraint.
_fc = sqlite3.connect(_fdb)
_ins = ("INSERT INTO tasks(id,title,instruction,predicate_src,predicate_sha,tz,"
        "origin_kind,origin_transport,origin_id,requester_uid,created_at,updated_at) "
        "VALUES(?, 't','i','x','x','UTC',?,?,'C123','Ada',0,0)")


def _check_rejects(tid, kind, transport):
    try:
        _fc.execute(_ins, (tid, kind, transport))
        return False
    except sqlite3.IntegrityError as e:
        return "CHECK constraint failed" in str(e)


_fc.execute(_ins, ("tsk_ok_pair", "channel", "slack"))
check("CONTROL: the fresh table accepts ('channel', 'slack') through a raw insert",
      _fc.execute("SELECT COUNT(*) FROM tasks WHERE id='tsk_ok_pair'").fetchone()[0] == 1)
check("TEETH: the fresh table's CHECK rejects ('channel', NULL)",
      _check_rejects("tsk_no_transport", "channel", None))
check("the fresh table's CHECK rejects ('session', 'slack')",
      _check_rejects("tsk_session_transport", "session", "slack"))
check("the fresh table's CHECK rejects the legacy kind ('slack_channel', 'slack')",
      _check_rejects("tsk_legacy_kind", "slack_channel", "slack"))
_fc.close()

rc, out, _ = cli_at(_hf, "show", _add16(_hf, "chatx:channel:XC125")[3])
check("show names the transport beside the origin", "origin      XC125 via=chatx" in out,
      out[:300])

# --- (c) one reader, one grammar ------------------------------------------------------
check("decode_origin reads the legacy vocabulary",
      [s.decode_origin({"origin_kind": k}) for k in ("slack_channel", "slack_dm",
                                                     "slack_thread", "session")]
      == [("slack", "channel"), ("slack", "dm"), ("slack", "thread"), (None, "session")])
check("decode_origin reads the fresh vocabulary",
      s.decode_origin({"origin_kind": "dm", "origin_transport": "chatx"}) == ("chatx", "dm")
      and s.decode_origin({"origin_kind": "session", "origin_transport": None})
      == (None, "session"))
check("the legacy and the transport forms of --origin parse to the same origin",
      s.parse_origin("slack:C123") == s.parse_origin("slack:channel:C123")
      == ("slack", "channel", "C123", None)
      and s.parse_origin("dm:D123") == s.parse_origin("slack:dm:D123")
      == ("slack", "dm", "D123", None))
check("an inline thread makes the kind `thread`, for a channel and for a dm",
      s.parse_origin(f"slack:channel:C123:{_T1}") == ("slack", "thread", "C123", _T1)
      and s.parse_origin(f"slack:dm:D123:{_T1}") == ("slack", "thread", "D123", _T1))
check("--thread keeps its meaning: a channel becomes a thread, a dm stays a dm",
      s.parse_origin("slack:C123", _T1) == ("slack", "thread", "C123", _T1)
      and s.parse_origin("dm:D123", _T1) == ("slack", "dm", "D123", _T1))
for _bad in ("slack:channel:C123:", "a:b:c:d:e", "slack:channel:", "session:x"):
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            s.parse_origin(_bad)
        _code = None
    except SystemExit as e:
        _code = e.code
    check(f"parse_origin refuses {_bad!r} with exit 2", _code == 2, f"code={_code}")

# --- (d) the emit line says which transport the answer goes out on --------------------
_vrow = {"id": "tsk_v", "title": "t", "instruction": "i", "origin_kind": "slack_channel",
         "origin_id": "C123", "origin_thread": _T1, "origin_label": "#ops",
         "requester_uid": "Ada", "reason": "r"}
check("a legacy Slack row emits `origin=<id>(<label>) via=slack thread=<id>`, in order",
      f"origin=C123(#ops) via=slack thread={_T1} " in s.format_emit(_vrow, 1, 0),
      s.format_emit(_vrow, 1, 0))
check("a fresh row emits its own transport",
      " via=chatx " in s.format_emit(dict(_vrow, origin_kind="thread",
                                          origin_transport="chatx"), 1, 0))
check("a session origin carries no via=",
      "via=" not in s.format_emit(dict(_vrow, origin_kind="session", origin_id="-",
                                       origin_thread=None, origin_label=None), 1, 0))

# --- (e) the default requester pattern is the working transports' user ids ------------
_lean_req = json.loads(json.dumps(_BASE))
_lean_req["requester"] = {"directory_file": None, "directory_key": None}
_WORKING = {d["name"]: d for d in FIXTURE_TRANSPORTS.values() if d["status"] == "working"}
_EXPECTED_PATTERN = "|".join(f"(?:{_WORKING[n]['ids']['user']})" for n in sorted(_WORKING))
rc, out, err = run_with_cfg(_lean_req, "print(m.requester_id_pattern())", script=_SCRIPT_FT)
check("the default requester pattern is the alternation over the working descriptors",
      rc == 0 and out == _EXPECTED_PATTERN, f"rc={rc} out={out!r} want={_EXPECTED_PATTERN!r} "
                                            f"err={err[-160:]}")
check("CONTROL: the expectation itself covers two transports and leaves the placeholder "
      "out", _EXPECTED_PATTERN.count("(?:") == 2 and "17,20" not in _EXPECTED_PATTERN,
      _EXPECTED_PATTERN)
_patch_req = {"requester": _lean_req["requester"]}
for _who, _shape, _want_refused in (("UNOTINROSTER", "a slack user id", True),
                                    ("X12345", "a chatx user id", True),
                                    ("123456789012345678", "a placeholder's user id", False)):
    rc, out, err, _ = _add16(os.path.join(_m_tmp.name, "o_req_" + _who), "session",
                             requester=_who, cfg_patch=_patch_req)
    check(f"with the default pattern, {_shape} the directory cannot resolve is "
          + ("REFUSED" if _want_refused else "stored as a name"),
          (rc != 0 and "REFUSED" in out + err) if _want_refused else rc == 0,
          f"rc={rc} {(out + err)[-160:]}")
rc, out, err, _ = _add16(os.path.join(_m_tmp.name, "o_req_explicit"), "session",
                         requester="UNOTINROSTER",
                         cfg_patch={"requester": dict(_lean_req["requester"],
                                                      id_pattern="^Z+$")})
check("CONTROL: an explicit requester.id_pattern replaces the derived one",
      rc == 0, f"rc={rc} {(out + err)[-160:]}")

# --- (L) a dead daemon's lock is not a held lock: doctor and installation/check -------
# The lock FILE outlives the daemon (only the flock is released), and so does the pid
# written into it. doctor's `lock holder` line printed that pid whenever the file
# existed, and installation/check said "a daemon holds the lock" for the file alone:
# both reported a scheduler armed after it was gone. Both now make a non-blocking
# flock attempt. THREE STATES, each driven for real: no file; a leftover file with a
# dead pid and no holder; a LIVE holder (a process that took the flock, as the daemon
# does). The live holder is the control that makes the leftover verdict mean
# something: an instrument that cannot report "held" proves nothing by not reporting it.
import fcntl  # noqa: E402
import socket  # noqa: E402

_L = tempfile.mkdtemp(prefix="sched-lock-")
_L_INSTALL = os.path.join(_L, "install")
_L_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(_SCRIPT)))))
os.makedirs(os.path.join(_L_INSTALL, ".claude", "skills", "scheduled-tasks", "installation"))
shutil.copy2(os.path.join(_L_REPO, "tests", "fixtures", "install", ".claude", "fleet.json"),
             os.path.join(_L_INSTALL, ".claude", "fleet.json"))
_L_OWNER = os.path.join(_L, "owner", ".claude")
_L_DB = os.path.join(_L, "db", "tasks.db")
os.makedirs(os.path.dirname(_L_DB), mode=0o700)
os.chmod(os.path.dirname(_L_DB), 0o700)
_L_CFG = os.path.join(_L, "scheduler.json")
_l_cfg = json.loads(json.dumps(_BASE))
_l_cfg["owner"]["claude_config_dir"] = _L_OWNER
_l_cfg["db"]["path"] = _L_DB
_l_cfg["defaults"]["tz"] = "UTC"
with open(_L_CFG, "w") as f:
    json.dump(_l_cfg, f)
os.chmod(_L_CFG, 0o600)
with open(os.path.join(os.path.dirname(_SCRIPT), "SKILL.md")) as f:
    _l_version = int(next(ln.split(":")[1] for ln in f if ln.startswith("version:")))
with open(os.path.join(_L_INSTALL, ".claude", "skills", "scheduled-tasks", "installation",
                       ".install-state.json"), "w") as f:
    json.dump({"hosts": {socket.gethostname(): {_L_OWNER: {"version": _l_version}}}}, f)
_L_LOCK = _L_DB + ".lock"
_L_ENV = {**os.environ, "SCHED_CONFIG": _L_CFG, "FLEET_CONTEXT_ROOT": _L_INSTALL, "HOME": _L}
_L_CHECK = os.path.join(os.path.dirname(_SCRIPT), "installation", "check")


def _lock_readings():
    """(check's OK line, doctor's lock holder line, doctor's armed line)."""
    rc_c = subprocess.run([sys.executable, _L_CHECK], capture_output=True, text=True, env=_L_ENV)
    rc_d = subprocess.run([sys.executable, _SCRIPT_FT, "doctor"], capture_output=True, text=True, env=_L_ENV)
    holder = next((ln for ln in rc_d.stdout.splitlines() if ln.startswith("lock holder")), "<no holder line>")
    armed = next((ln for ln in rc_d.stdout.splitlines() if ln.startswith("armed")), "<no armed line>")
    return f"exit {rc_c.returncode}: {rc_c.stdout.strip()}{rc_c.stderr.strip()[-200:]}", holder, armed


line, holder, armed = _lock_readings()
check("no lock file: the check says the lock file is absent and doctor is not armed",
      "exit 0: OK" in line and "lock file absent" in line and armed.startswith("armed        NO")
      and holder == "<no holder line>", f"{line} | {holder} | {armed}")
with open(_L_LOCK, "w") as f:
    f.write("999999\n")              # the pid a daemon that is gone wrote into the file
os.chmod(_L_LOCK, 0o600)
line, holder, armed = _lock_readings()
check("TEETH: a leftover lock file with no holder: the check does NOT say a daemon holds the lock",
      "exit 0: OK" in line and "a daemon holds the lock" not in line and "no daemon holds the lock" in line,
      line)
check("TEETH: ...and doctor names no holder, only the dead pid the file still carries, and is not armed",
      holder == "lock holder  none: no process holds the lock (the file names pid 999999, a daemon that is gone)"
      and armed.startswith("armed        NO"), f"{holder} | {armed}")
_holder = subprocess.Popen(
    [sys.executable, "-c",
     "import fcntl, os, sys, time\n"
     "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
     "fcntl.flock(fd, fcntl.LOCK_EX)\n"
     "os.ftruncate(fd, 0); os.write(fd, f'{os.getpid()}\\n'.encode())\n"
     "print('held', flush=True)\n"
     "time.sleep(120)\n", _L_LOCK],
    stdout=subprocess.PIPE, text=True)
try:
    _held = _holder.stdout.readline().strip() == "held"
    line, holder, armed = _lock_readings()
    check("CONTROL: a live holder of the flock: the check says a daemon holds the lock",
          _held and "exit 0: OK" in line and "a daemon holds the lock" in line, line)
    check("CONTROL: ...and doctor names the holder's pid and is armed",
          holder == f"lock holder  pid {_holder.pid}" and armed == "armed        yes", f"{holder} | {armed}")
finally:
    _holder.kill()
    _holder.wait()
    _holder.stdout.close()
shutil.rmtree(_L)

_m_tmp.cleanup()
_ft_tmp.cleanup()


_tmp.cleanup()

print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
