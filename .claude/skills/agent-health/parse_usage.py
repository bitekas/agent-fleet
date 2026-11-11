#!/usr/bin/env python3
"""Parse a captured Claude Code /usage screen and say whether the session has
crossed a handover threshold - on the floor, or on its projected depletion.

WHY THIS EXISTS AS A SCRIPT AND NOT AS AN EYEBALL
-------------------------------------------------
The whole point of agent-health is to move an agent onto another account BEFORE
it hits a cap. The decision is therefore made at a boundary - 89 vs 90, 94 vs
95, a projection that lands 58 minutes out against one that lands 62 - and a
boundary read by eye off a bar chart is read wrong at exactly the moments it
matters. This script turns the pane text into numbers so the rule is applied
and not estimated.

THE TWO RULES, AND WHY THE SECOND ONE NEEDS A LEDGER
----------------------------------------------------
* THE FLOOR: a SHORT window at >= 90%, any other limit at >= 95%. It is read
  off one capture, it needs no history, and it fires on sight. It is the
  backstop for usage that arrived faster than two readings could see it.

* THE PROJECTION: velocity is the change in percent since that window's
  previous reading, per hour; projected depletion is `now + (100 - %) /
  velocity`. An agent is switched when the projection lands within 60 minutes
  on TWO CONSECUTIVE checks AND the window's reset falls after that moment.

  Two checks, because one pair of readings is a slope through two points and a
  single burst of work draws a slope that says an hour. The reset condition,
  because a window that resets before it would have depleted empties itself:
  switching an agent to dodge a cap that was never going to land costs a
  handover and buys nothing.

  Both need the previous reading, which is what `--ledger` supplies. A ledger
  is therefore REQUIRED unless `--floor-only` is passed explicitly, and a
  floor-only run has its own verdict and its own exit code (4). It is not the
  same answer as `ok` and it is not reported as one: collapsed into `ok`/0 it
  would be byte-identical, to a caller reading `$?`, to a fully projected clean
  sweep - the same "green for ever while measuring nothing" outcome the
  missing-ledger refusal below exists to prevent, reached through the front
  door by forgetting a flag.

VELOCITY IS PER WINDOW, AGAINST THE SAME WINDOW'S OWN PREVIOUS ROW
------------------------------------------------------------------
A session window and a weekly window fill at different rates. A velocity taken
across two different windows is a number that looks entirely reasonable and
means nothing, so the previous row is matched on the window NAME and on the
ACCOUNT both:

  * NAME, because that is what identifies the window. ⚠️ Names move between
    Claude Code versions, so a renamed window finds no previous row and is
    recorded as a first reading - no projection, no action. The floor still
    applies to it on sight, which is the fail-safe direction: a rename costs
    the early warning, never the backstop.
  * ACCOUNT, because a handover resets the usage. Comparing a reading on the
    new account against one on the old produces a velocity computed across a
    discontinuity - harmless when the new account starts lower, actively wrong
    when it starts higher. A row whose account differs from the previous row's
    is a first reading.

THE FIVE OUTCOMES, AND WHY THEY MAY NEVER BE COLLAPSED
-------------------------------------------------------
`verdict` is one of:

  trigger       at least one limit must be acted on -> run the handover
                procedure in SKILL.md. Exit 1.
  ok            every limit was read and none of them needs acting on. Exit 0.
  inconclusive  the instrument did not reach its subject. Exit 3.
  floor-only    the floor was applied and the projection was not, because no
                ledger was given. Exit 4. A smaller claim than `ok`.

and a fifth state lives in the exit code alone:

  exit 2        THE INSTRUMENT COULD NOT BE SET UP - a ledger path that does
                not exist, a ledger that cannot be parsed, a missing `--agent`
                or `--account`, an unreadable capture, or ANY unexpected
                exception. It pronounces on no agent.
                ⚠️ The catch-all matters: an uncaught traceback exits 1, which
                is the published contract for HAND THIS AGENT OVER, so without
                it a `--ledger` naming a directory or an `--init` into a
                missing directory reaches a caller as the loudest verdict this
                script has.

`inconclusive` is the load-bearing one and it is NOT a synonym for `ok`, and it
covers THREE distinct ways the instrument misses its subject:

  * no limit parsed at all - the send-keys never landed, the pane was still
    drawing, the session was on a different tab, the capture came from the
    wrong pane, or a future Claude Code renamed the screen;
  * a limit with NO NAME above it - the capture is cut at the top, or the
    dialog is taller than the pane. `tmux capture-pane -p` returns the visible
    pane, so this is ordinary. Reported as a verdict it becomes a row whose key
    nothing can ever match again, and that window is then a `first-reading` on
    every sweep for ever while the run says `ok`;
  * a window the PREVIOUS sweep recorded and this capture does not - one
    wrapped `NN% used` line drops a window from the sweep, and if it was the
    window sitting on a `watch` it disappears with the verdict still `ok`.
    ⚠️ A limit Claude Code genuinely retires lands here too and stays
    inconclusive until a person looks. That is the intended cost: only a person
    can tell a product change from a half-drawn pane.

Every one of those is "the instrument did not reach the subject",
and the comfortable reading of every one of them is "nothing is wrong". If this
script reported `ok` there, the sweep would go green forever on an agent it had
stopped measuring, which is precisely the failure agent-health exists to
prevent. So: **an inconclusive reading issues no verdict about the agent** -
re-capture, and if it persists, read the pane by hand. Do not treat it as
healthy and do not let a caller coerce it to a boolean. ⚠️ An inconclusive
capture also APPENDS NOTHING, even under `--append`: a row invented from a
capture that read nothing becomes the baseline the next sweep's velocity is
computed against, so one unread pane would silently poison the projection for
every reading after it.

THE SECOND INPUT: A TOKEN AGENT'S RATE-LIMIT SNAPSHOT (--rate-limits)
---------------------------------------------------------------------
An agent that runs on a long-lived token (`claude setup-token`, the `token`
auth mode) cannot be read off /usage at all: that dialog fetches its plan rows
only for an OAuth sign-in carrying the `user:profile` scope, and a setup-token
token carries `user:inference` alone (Claude Code 2.1.317 binary; measured the
same day on a session started with an env token: the dialog drew the Session
block and no limit). The same session's STATUS LINE input does carry
`rate_limits.five_hour` and `rate_limits.seven_day`, filled from the response
headers of its own inference calls, with no scope check (the same binary).
`usage_statusline.py`, beside this file, is that agent's status-line command:
it keeps the last reading of each window in `<config dir>/fleet-usage.json`.
`--rate-limits <config dir>` reads that file instead of a capture and builds the
SAME limits a capture yields - `Current session` (five_hour, a SHORT window)
and `Current week (all models)` (seven_day, a LONG one), with their resets
written in the screen's own shape - so the ledger, the velocity, the floor, the
projection and the picker treat both sources alike. A window whose reset has
passed since the reading is reported at 0%: the agent has taken no turn since
(a turn would have rewritten the file), and one account is live in one session,
so nothing else spent it. A missing snapshot is `inconclusive`, never `ok`.

`fixtures/status-screen.txt` is the negative control for this: it is a real
capture of the /status tab, i.e. the same dialog with the same tab bar and the
same footer but no limits on it. It must come back `inconclusive`. If it ever
comes back `ok`, this parser has stopped being able to tell "measured and fine"
from "measured nothing", and every verdict it has ever issued is worthless.
`parse_usage.test.sh` pins that. Do not delete that case to tidy the suite.

⚠️ A MISSING LEDGER FILE IS EXIT 2 AND NOT A FIRST READING, AND THAT REFUSAL IS
THE POINT. A mistyped `--ledger` path reads, otherwise, as an agent with no
history: every window comes back `first-reading`, every sweep is recorded and
none is ever acted on, and the sweep reports a healthy fleet forever while
measuring nothing at all - the same failure as a silent `inconclusive`, arriving
through the other door. The ledger is created ONCE, deliberately, with `--init`;
after that its absence is an instrument fault and says so. Do not "fix" a
missing-ledger exit 2 by making the script create the file.

WINDOW CLASSIFICATION
---------------------
The thresholds differ by window (short 90%, long 95%), so each limit has to be
classified. It is done off the `Resets` line and NOT off the limit's NAME:

  Resets 1:20am (UTC)        -> a time of day, no date  -> SHORT window
  Resets Sep 23, 8pm (UTC)   -> carries a date          -> LONG window

Names move between Claude Code versions and between plans ("Current session",
"Current week (all models)", "Current week (<model>)" today; a plan with a
literally-named daily limit tomorrow). The reset SHAPE is what actually encodes
how long the window is, so it is the thing to read. A limit whose Resets line
this script cannot classify is treated as SHORT - the stricter threshold - and
flagged `window: "unknown"`. Fail-safe is triggering a handover slightly early,
never missing one.

The same line is also resolved to an ABSOLUTE time, for the reset-versus-
depletion comparison. ⚠️ A reset this script cannot resolve to an absolute time
(a timezone other than UTC, an unparseable shape) is treated as LATER than any
projection - so the projection still trips. Fail-safe again: an unreadable reset
costs a handover that may not have been needed, never a cap that was.
"""

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

SHORT_WINDOW_THRESHOLD = 90   # "daily"/session-scoped windows: hand over at >= 90%
LONG_WINDOW_THRESHOLD = 95    # every other window: hand over at >= 95%
DEPLETION_HORIZON_MIN = 60    # a projection landing within this many minutes trips
# ⚠️ A SLOPE THROUGH TWO READINGS MINUTES APART IS NOISE AMPLIFIED, NOT A RATE.
# The ledger stamps to the MINUTE while the clock does not, so two readings 30
# seconds apart differ by one recorded minute and a single percentage point
# becomes 120 %/h - enough to project depletion inside the horizon on an idle
# agent. Two such readings in a row switch it. A sweep runs twice close together
# routinely (a session-start sweep followed by the scheduled one), so this is
# ordinary rather than adversarial input. Below this interval no slope is
# computed at all.
MIN_INTERVAL_SECS = 300

PERCENT_RE = re.compile(r"(\d{1,3})%\s+used\b")
RESETS_RE = re.compile(r"^\s*Resets\b\s*(.*)$")
# A reset that is a bare time of day ("1:20am", "13:20", "8pm") is the SHORT
# window. ⚠️ THE BARE-HOUR FORM IS HERE ON PURPOSE AND WAS MISSING: `8pm`
# resolves perfectly well to an absolute time below, so leaving it out of the
# CLASSIFIER made the two halves disagree about the same string - it resolved as
# a time of day and classified as `unknown`. Fail-safe either way (unknown takes
# the stricter threshold), but two readers of one string must not disagree.
TIME_ONLY_RE = re.compile(r"^\d{1,2}(:\d{2})?\s*(am|pm)\b|^\d{1,2}:\d{2}\b",
                          re.IGNORECASE)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

TZ_SUFFIX_RE = re.compile(r"\(([^)]+)\)\s*$")
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.IGNORECASE)
DATE_TIME_RE = re.compile(
    r"^(%s)\s+(\d{1,2})\s*,\s*(.+)$" % "|".join(MONTHS), re.IGNORECASE)

TIME_FMT = "%Y-%m-%dT%H:%MZ"

# The token agent's rate-limit snapshot (module docstring, THE SECOND INPUT):
# the file usage_statusline.py writes in the agent's Claude config dir, and the
# windows it carries, each with the name and window shape a /usage capture
# gives the same limit, and the period a passed reset rolls forward by (None:
# the next window starts at the next turn, so its reset is unknown).
SNAPSHOT_NAME = "fleet-usage.json"
SNAPSHOT_WINDOWS = (("five_hour", "Current session", "short", None),
                    ("seven_day", "Current week (all models)", "long", 7 * 86400))

LEDGER_COLUMNS = ["time", "account", "window", "% used", "resets at",
                  "velocity %/h", "projected depletion", "decision"]

LEDGER_PREAMBLE = """# agent usage ledger

One section per agent, one row per window read. `parse_usage.py --ledger <this
file> --agent <name> --append` writes the rows and reads the previous ones back
out of them; nothing else may write here, because the previous row IS the
baseline every velocity and every projection is computed against.

`velocity %/h` is the change in `% used` since that window's previous row on the
SAME account, per hour. `projected depletion` is `time + (100 - % used) /
velocity`. `decision` is one of:

| decision | means |
|---|---|
| `first-reading` | no comparable previous row (new agent, new window name, or a new account after a handover). Recorded, not acted on. |
| `ok` | read, and nothing to do: flat or falling usage, or a projection beyond the horizon. |
| `watch` | the projection landed within the horizon for the FIRST time. One more consecutive one switches the agent. A later reading that produces no projection at all CARRIES this forward rather than clearing it - these agents alternate between a burst and idle, and clearing it made the rule inert for exactly them. |
| `hold-reset-first` | the projection landed within the horizon, but the window resets before it would deplete, so the window empties itself. |
| `switch-projection` | the projection landed within the horizon on two consecutive checks with the reset after it. Hand the agent over. |
| `switch-floor` | at or over the absolute floor (short window 90%, any other 95%). Hand the agent over, whatever the velocity says. |
| `floor-only` | evaluated with no ledger, so only the floor was applied. NOT the same claim as `ok`. |

⚠️ Do not delete or rewrite rows to tidy this file. A removed row is a velocity
that cannot be computed and a projection that silently stops existing; an edited
one is a baseline that lies. It grows, and that is the intended shape.
"""


def _strip(line):
    return line.rstrip()


# --------------------------------------------------------------------------
# reset-line resolution
# --------------------------------------------------------------------------

def _month_index(name):
    for i, mon in enumerate(MONTHS, start=1):
        if mon.lower() == name.lower():
            return i
    return None


def _parse_clock(body):
    """'1:20am' / '13:20' / '8pm' -> (hour, minute) in 24h, or None."""
    m = TIME_RE.match(body.strip())
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "am":
        if hour == 12:
            hour = 0
    elif ampm == "pm":
        if hour != 12:
            hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def resolve_reset(resets, now_epoch):
    """Resolve a `Resets ...` value to an absolute epoch, or None.

    None means "could not be established", and every caller treats that as
    LATER than any projection (see the module docstring's fail-safe note).
    """
    if not resets:
        return None
    text = resets.strip()
    m = TZ_SUFFIX_RE.search(text)
    # ⚠️ AN EXPLICIT UTC MARKER IS REQUIRED, AND ITS ABSENCE IS NOT UTC.
    # Rejecting a NAMED non-UTC zone while silently assuming UTC when no zone is
    # printed at all covers the case that announces itself and misses the one
    # that does not: a future build printing local time would resolve up to 24
    # hours out in EITHER direction, and the early direction produces
    # `hold-reset-first` - the handover that should have happened, not
    # happening. Unresolved counts as LATER than any projection, so an absent
    # zone costs a handover that may not have been needed, never a cap that was.
    if not m:
        return None
    tzname = m.group(1).strip().upper()
    if tzname not in ("UTC", "GMT", "Z"):
        return None
    text = text[:m.start()].strip().rstrip(".,")

    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc)

    dm = DATE_TIME_RE.match(text)
    if dm:
        month = _month_index(dm.group(1))
        day = int(dm.group(2))
        clock = _parse_clock(dm.group(3))
        if month is None or clock is None:
            return None
        for year in (now.year, now.year + 1):
            try:
                cand = datetime(year, month, day, clock[0], clock[1],
                                tzinfo=timezone.utc)
            except ValueError:
                # `continue`, not `return`: Feb 29 is invalid in one candidate
                # year and valid in the next, and returning here refused a date
                # the following year would have resolved.
                continue
            if cand >= now:
                return cand.timestamp()
        return None

    clock = _parse_clock(text)
    if clock is None:
        return None
    cand = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if cand < now:
        cand += timedelta(days=1)
    return cand.timestamp()


# --------------------------------------------------------------------------
# the capture
# --------------------------------------------------------------------------

def classify_window(resets):
    """'short' | 'long' | 'unknown', off the shape of a `Resets` value.

    The ONE statement of the rule in the module docstring's WINDOW
    CLASSIFICATION section. pool_pick.py imports it to find an account's
    weekly rows in the ledger, so the parser and the picker cannot disagree
    about which window a row is.
    """
    if TIME_ONLY_RE.match(resets):
        return "short"
    if any(mon in resets for mon in MONTHS):
        return "long"
    return "unknown"


def _clock(dt):
    """'1:20am' - the screen's own clock shape, which resolve_reset reads."""
    return "%d:%02d%s" % (dt.hour % 12 or 12, dt.minute, "am" if dt.hour < 12 else "pm")


def format_reset(epoch, window):
    """An absolute reset time in the shape /usage prints for that window."""
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    if window == "short":
        return "%s (UTC)" % _clock(dt)
    return "%s %d, %s (UTC)" % (MONTHS[dt.month - 1], dt.day, _clock(dt))


def _limit(name, percent, window, resets):
    threshold = LONG_WINDOW_THRESHOLD if window == "long" else SHORT_WINDOW_THRESHOLD
    return {"name": name, "percent": percent, "window": window, "resets": resets,
            "threshold": threshold, "over": percent >= threshold}


class SnapshotError(Exception):
    """The snapshot exists and cannot be read. Exit 2, like a bad ledger."""


def read_snapshot(config_dirs, now_epoch):
    """(limits, reason) from a token agent's rate-limit snapshot.

    `config_dirs` is one config dir, or several when the agents behind them share
    one account (a SHARED lease, pool_pick.py): every holder's turns move the
    account's usage, and each snapshot is as fresh as its own agent's last
    answer, so the one written LAST is the account's state and is the one read.
    limits is None when there is no snapshot to read - an `inconclusive`, with
    `reason` saying why. A snapshot that exists and is not the shape
    usage_statusline.py writes raises SnapshotError.
    """
    if isinstance(config_dirs, str):
        config_dirs = [config_dirs]
    paths = [os.path.join(d, SNAPSHOT_NAME) for d in config_dirs]
    snaps = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                snaps.append((json.load(fh), path))
        except (OSError, ValueError) as exc:
            raise SnapshotError("cannot read the snapshot %s: %s" % (path, exc))
    if not snaps:
        return None, ("no rate-limit snapshot at %s - the agent's status line is not "
                      "usage_statusline.py, or the session has taken no turn since "
                      "it started. This is NOT a healthy reading." % ", ".join(paths))
    snap, path = max(snaps, key=lambda s: (s[0].get("written_at") or 0)
                     if isinstance(s[0], dict) else 0)
    rl = snap.get("rate_limits") if isinstance(snap, dict) else None
    if not isinstance(rl, dict):
        raise SnapshotError("the snapshot %s carries no rate_limits object" % path)
    limits = []
    for key, name, window, period in SNAPSHOT_WINDOWS:
        w = rl.get(key)
        if w is None:
            continue
        try:
            pct = int(round(float(w["used_percentage"])))
            reset = float(w["resets_at"])
        except (KeyError, TypeError, ValueError):
            raise SnapshotError("the snapshot %s: rate_limits.%s needs a numeric "
                                "used_percentage and resets_at" % (path, key))
        if reset <= now_epoch:
            pct = 0
            if period is None:
                limits.append(_limit(name, pct, window, "-"))
                continue
            reset += (int((now_epoch - reset) // period) + 1) * period
        limits.append(_limit(name, pct, window, format_reset(reset, window)))
    if not limits:
        return None, ("the snapshot %s holds no window yet - the session has not had "
                      "an answer from the API since it started" % path)
    return limits, ""


def parse_limits(text):
    lines = [_strip(l) for l in text.splitlines()]
    limits = []

    for i, line in enumerate(lines):
        m = PERCENT_RE.search(line)
        if not m:
            continue
        percent = int(m.group(1))

        # The name is the nearest non-blank line above that is not itself a
        # percentage line and not a Resets line.
        name = ""
        for j in range(i - 1, -1, -1):
            candidate = lines[j].strip()
            if not candidate:
                continue
            if PERCENT_RE.search(candidate) or RESETS_RE.match(candidate):
                continue
            name = candidate
            break

        # The window is read off the nearest Resets line below, before the next
        # percentage line.
        resets = ""
        for j in range(i + 1, len(lines)):
            if PERCENT_RE.search(lines[j]):
                break
            rm = RESETS_RE.match(lines[j])
            if rm:
                resets = rm.group(1).strip()
                break

        limits.append(_limit(name, percent, classify_window(resets), resets))
    return limits


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

class LedgerError(Exception):
    """The ledger cannot be used. Never a verdict about an agent."""


def _cell(value):
    """Normalise a value for the table - and this is the ONLY normalisation.

    ⚠️ THE WRITER AND THE READER MUST USE THE SAME FUNCTION, AND THE FIRST
    VERSION OF THIS FILE DID NOT. `_cell` mapped an empty window name to "-"
    on the way in while the lookup asked for "", so the two never matched and
    that window came back `first-reading` on every sweep for ever - recorded
    each time, projected never, verdict `ok`, exit 0. The same shape bit any
    name containing "|", which is mapped to "/" here and was looked up with the
    "|" still in it. A key is normalised once, by this function, on both sides.
    """
    return str(value).replace("|", "/").replace("\n", " ").strip() or "-"


def read_ledger_rows(path, agent):
    """Every row recorded for `agent`, oldest first.

    Raises LedgerError on a row this cannot parse. ⚠️ A SILENT `continue` HERE
    IS A HANDOVER DOWNGRADED TO A WAIT. A malformed row is skipped, an OLDER
    row becomes the baseline, and the velocity computed off it is smaller - so
    a `switch-projection` is delivered as a `watch` with nothing red anywhere.
    Nothing but this script may write the file, so a row it cannot read means
    the file was hand-edited, and that is a fact about the instrument.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    want = "## " + agent
    rows = []
    in_section = False
    for n, line in enumerate(lines, start=1):
        stripped = line.strip()
        # ⚠️ ANY heading closes the section, not just another `## `. Otherwise a
        # `### notes` an operator adds under an agent leaves the section open, and
        # the rows under it are read as that agent's readings.
        if stripped.startswith("#"):
            in_section = (stripped == want)
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) == len(LEDGER_COLUMNS) and (
                cells[0] == LEDGER_COLUMNS[0] or set(cells[0]) <= set("-: ")):
            continue  # the header row and the separator
        if len(cells) != len(LEDGER_COLUMNS):
            raise LedgerError(
                "%s:%d: a row in section '%s' has %d cells, expected %d. "
                "Nothing but parse_usage.py writes this file, so this row was "
                "hand-edited. Skipping it would make an OLDER row the velocity "
                "baseline and quietly downgrade a handover to a wait: %s"
                % (path, n, agent, len(cells), len(LEDGER_COLUMNS), stripped))
        rows.append({
            "line": n,
            "time": cells[0],
            "account": cells[1],
            "window_name": cells[2],
            "percent": cells[3],
            "resets": cells[4],
            "velocity": cells[5],
            "projected_depletion": cells[6],
            "decision": cells[7],
        })
    return rows


def last_sweep_windows(rows, account):
    """The window names the most recent sweep on `account` recorded.

    Used to notice that a window this agent HAS has gone missing from a
    capture - see the partial-capture guard in `analyse`.
    """
    stamps = [r["time"] for r in rows if r["account"] == account]
    if not stamps:
        return set()
    latest = max(stamps)
    return {r["window_name"] for r in rows
            if r["account"] == account and r["time"] == latest}


def previous_row(rows, window_key, account):
    """The last row for this window ON THE SAME ACCOUNT, or None.

    Matching on the account too is what stops a velocity being computed across
    a handover, where the usage counter restarts.
    """
    for row in reversed(rows):
        if row["window_name"] != window_key:
            continue
        if row["account"] != account:
            return None
        try:
            int(row["percent"])
            datetime.strptime(row["time"], TIME_FMT)
        except ValueError:
            return None
        return row
    return None


def lock_ledger(path):
    """Take an exclusive lock for a read-modify-write of the ledger.

    ⚠️ THE APPEND IS A WHOLE-FILE READ-MODIFY-WRITE AND THE SWEEP CAN OVERLAP
    ITSELF. One ledger serves the whole fleet, and the charter says in so many
    words that a sweep still carries on while a handover from an earlier cycle
    is in flight - so two invocations racing is designed behaviour, not an
    edge case. Unlocked, the second one's read predates the first one's write
    and a row is lost; a lost row is the same outcome as a row that could not
    be parsed, an older baseline and a handover quietly downgraded to a wait.
    The lock is a separate file so that the ledger itself can be replaced
    atomically underneath it.
    """
    fh = open(path + ".lock", "a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def append_rows(path, agent, rows):
    """Append `rows` under the agent's section, creating the section if new.

    Written through a temporary file and renamed into place: a crash part way
    through a direct rewrite truncates the ledger, and a truncated ledger is a
    fleet with no velocity baselines at all.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    header = "| " + " | ".join(LEDGER_COLUMNS) + " |"
    sep = "|" + "|".join(["---"] * len(LEDGER_COLUMNS)) + "|"
    block = "\n".join("| " + " | ".join(_cell(c) for c in row) + " |"
                      for row in rows)

    section = "## " + agent
    lines = text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip() == section:
            idx = i
            break

    if idx is None:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n" + section + "\n\n" + header + "\n" + sep + "\n" + block + "\n"
    else:
        end = len(lines)
        for i in range(idx + 1, len(lines)):
            if lines[i].strip().startswith("## "):
                end = i
                break
        while end > idx + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = block.splitlines()
        text = "\n".join(lines) + "\n"

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".agents-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

# The previous decisions that count as "this window already tripped the
# projection once". `switch-floor` is deliberately NOT in this set: it is the
# other rule's verdict, and a window at the floor trips the floor again anyway.
TRIPPED_BEFORE = ("watch", "switch-projection")


def decide(limit, prev, now_epoch):
    """Fill velocity / projection / decision onto one limit, in place."""
    limit["velocity_pct_per_hour"] = None
    limit["projected_depletion"] = None
    limit["minutes_to_depletion"] = None
    limit["resets_at"] = None
    limit["previous"] = None

    reset_epoch = resolve_reset(limit["resets"], now_epoch)
    if reset_epoch is not None:
        limit["resets_at"] = datetime.fromtimestamp(
            reset_epoch, tz=timezone.utc).strftime(TIME_FMT)

    # The floor is read off this capture alone and outranks everything below.
    if limit["over"]:
        floor = True
    else:
        floor = False

    if prev is None:
        limit["decision"] = "switch-floor" if floor else "first-reading"
        return

    prev_epoch = datetime.strptime(prev["time"], TIME_FMT).replace(
        tzinfo=timezone.utc).timestamp()
    limit["previous"] = {
        "time": prev["time"],
        "percent": int(prev["percent"]),
        "account": prev["account"],
        "decision": prev["decision"],
    }

    interval = now_epoch - prev_epoch
    if interval < MIN_INTERVAL_SECS:
        # A row from the future, two readings at the same minute, or two sweeps
        # minutes apart. No usable slope exists; refuse to invent one. See
        # MIN_INTERVAL_SECS - a guard of `hours <= 0` alone lets a thirty-second
        # gap turn one percentage point into 120 %/h.
        limit["decision"] = "switch-floor" if floor else "first-reading"
        return
    hours = interval / 3600.0

    velocity = (limit["percent"] - int(prev["percent"])) / hours
    # ⚠️ THE ROUNDED VELOCITY IS WHAT THE PROJECTION IS COMPUTED FROM, ON
    # PURPOSE. The ledger prints one decimal place, and a reader who recomputes
    # `now + (100 - %) / velocity` from the printed number must land on the
    # printed depletion - otherwise the row cannot be audited by the person it
    # is written for. The cost is that a creep below 0.05 %/h reads as exactly
    # flat; at that rate the depletion is two thousand hours out, so nothing
    # downstream can tell the difference.
    limit["velocity_pct_per_hour"] = round(velocity, 1)

    if floor:
        limit["decision"] = "switch-floor"
        return

    if limit["velocity_pct_per_hour"] <= 0:
        # Flat or falling usage projects no depletion at all.
        # ⚠️ A READING THAT PRODUCES NO PROJECTION DOES NOT CLEAR A STANDING
        # TRIP, AND CLEARING IT MADE THE WHOLE RULE INERT FOR THE AGENTS IT IS
        # FOR. These agents work a turn and then wait - on a subagent, a
        # monitor, a person - so their velocity alternates between a burst and
        # zero. With a zero reading resetting the consecutive counter, a
        # simulated bursty agent tripped the horizon three separate times, was
        # never switched, and met the floor at 100% with the cap already
        # landed. Absence of progress is not evidence of safety: the trip is
        # carried forward unchanged until a reading either confirms it or the
        # window resets.
        limit["decision"] = ("watch" if prev["decision"] in TRIPPED_BEFORE
                             else "ok")
        return

    remaining_hours = (100 - limit["percent"]) / limit["velocity_pct_per_hour"]
    depletion_epoch = now_epoch + remaining_hours * 3600.0
    limit["projected_depletion"] = datetime.fromtimestamp(
        depletion_epoch, tz=timezone.utc).strftime(TIME_FMT)
    limit["minutes_to_depletion"] = round(remaining_hours * 60.0, 1)

    if limit["minutes_to_depletion"] > DEPLETION_HORIZON_MIN:
        limit["decision"] = "ok"
        return

    # An unresolvable reset counts as LATER than the projection: the trip
    # stands. See the docstring's fail-safe note.
    if reset_epoch is not None and reset_epoch <= depletion_epoch:
        limit["decision"] = "hold-reset-first"
        return

    if prev["decision"] in TRIPPED_BEFORE:
        limit["decision"] = "switch-projection"
    else:
        limit["decision"] = "watch"


# --------------------------------------------------------------------------

def analyse(text, now_epoch, rows=None, account="-", have_ledger=False,
            limits=None, no_limits_reason=None):
    """`limits`, when given, replaces parsing `text` (the snapshot route)."""
    if limits is None and no_limits_reason is None:
        limits = parse_limits(text)
    if not limits:
        return {
            "verdict": "inconclusive",
            "reason": no_limits_reason or (
                      "no limit found on the capture - the instrument did not "
                      "reach the subject. This is NOT a healthy reading: "
                      "re-capture, and read the pane by hand if it persists."),
            "limits": [],
            "triggered": [],
        }

    # ⚠️ AN UNNAMED LIMIT MEANS THE CAPTURE IS CUT, NOT THAT THE LIMIT HAS NO
    # NAME. The name is the nearest non-blank line ABOVE the percentage, so an
    # empty one says the pane did not contain that line - a dialog taller than
    # the pane, or a scrolled one. `tmux capture-pane -p` returns the visible
    # pane, so this is an ordinary outcome. Reported as a verdict it becomes a
    # row whose key nothing can match again; reported as inconclusive it is what
    # it is, an instrument that half reached its subject.
    unnamed = [l for l in limits if not l["name"].strip()]
    if unnamed:
        return {
            "verdict": "inconclusive",
            "reason": "%d limit(s) on this capture have no name line above them "
                      "- the capture is cut off at the top, or the dialog is "
                      "taller than the pane. A nameless limit cannot be matched "
                      "against its own previous reading, so it would be a first "
                      "reading on every sweep for ever. Re-capture."
                      % len(unnamed),
            "limits": [],
            "triggered": [],
        }

    if have_ledger:
        # ⚠️ A WINDOW THIS AGENT HAD AND THIS CAPTURE DOES NOT IS A PARTIAL READ.
        # The inconclusive guard above is all-or-nothing, and "the instrument
        # reached SOME of the subject" is the state it cannot express: a single
        # wrapped `NN% used` line drops one window from the sweep, and if that
        # window was the one sitting on a `watch` it disappears with the verdict
        # still `ok`. Measured on the shipped fixtures by deleting one line.
        # ⚠️ A window Claude Code genuinely RETIRES also lands here, and stays
        # inconclusive until a person looks. That is the intended cost: a
        # vanished limit is either an instrument fault or a product change, and
        # only a person can tell which.
        seen = {_cell(l["name"]) for l in limits}
        missing = sorted(last_sweep_windows(rows or [], account) - seen)
        if missing:
            return {
                "verdict": "inconclusive",
                "reason": "this capture is missing %d window(s) the previous "
                          "sweep on this account recorded: %s. Either the "
                          "capture is partial - one wrapped or half-drawn line "
                          "is enough - or Claude Code has retired the limit. "
                          "Re-capture; if it persists, read the pane by hand. "
                          "This is NOT an ok sweep: a window that vanishes "
                          "silently is a window nobody is watching."
                          % (len(missing), ", ".join(missing)),
                "limits": [],
                "triggered": [],
            }

    for limit in limits:
        if have_ledger:
            decide(limit,
                   previous_row(rows or [], _cell(limit["name"]), account),
                   now_epoch)
        else:
            limit["velocity_pct_per_hour"] = None
            limit["projected_depletion"] = None
            limit["minutes_to_depletion"] = None
            limit["resets_at"] = None
            limit["previous"] = None
            limit["decision"] = "switch-floor" if limit["over"] else "floor-only"

    triggered = [l for l in limits if l["decision"].startswith("switch")]
    if triggered:
        verdict = "trigger"
    elif have_ledger:
        verdict = "ok"
    else:
        # ⚠️ `floor-only` IS ITS OWN VERDICT AND ITS OWN EXIT CODE (4), because
        # collapsing it into `ok`/0 makes an unprojected sweep byte-identical to
        # a projected clean one for any caller reading `$?` - which is how the
        # sweep is documented to call this. It is the same collapse this file
        # refuses for `inconclusive`, applied to the other degraded state. In
        # practice it is unreachable by accident: `--ledger` is required unless
        # `--floor-only` is asked for explicitly.
        verdict = "floor-only"
    return {
        "verdict": verdict,
        "reason": "",
        "limits": limits,
        "triggered": [l["name"] for l in triggered],
    }


def build_rows(result, now_epoch, account):
    stamp = datetime.fromtimestamp(now_epoch, tz=timezone.utc).strftime(TIME_FMT)
    rows = []
    for limit in result["limits"]:
        rows.append([
            stamp,
            account,
            limit["name"],
            limit["percent"],
            limit["resets"] or "-",
            "-" if limit["velocity_pct_per_hour"] is None
                else "%.1f" % limit["velocity_pct_per_hour"],
            limit["projected_depletion"] or "-",
            limit["decision"],
        ])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="parse_usage.py",
        description="Read a captured /usage screen and decide whether the "
                    "agent must be handed over.")
    ap.add_argument("capture", nargs="?",
                    help="the captured pane (default: stdin)")
    ap.add_argument("--agent", help="the agent this capture belongs to; "
                                    "required with --ledger")
    ap.add_argument("--ledger", help="the agents.md usage ledger. Its rows are "
                                     "the baseline for velocity and the "
                                     "projection; --append writes this "
                                     "reading back into it.")
    ap.add_argument("--account", default=None,
                    help="the account the agent is signed in as. REQUIRED with "
                         "--ledger: a reading on a different account is never "
                         "compared with this one, so a defaulted account "
                         "silently reads every window as a first reading.")
    ap.add_argument("--floor-only", action="store_true",
                    help="evaluate the FLOOR alone, with no ledger and no "
                         "projection. The verdict is `floor-only`, exit 4 - "
                         "never `ok`.")
    ap.add_argument("--append", action="store_true",
                    help="append this reading's rows to the ledger")
    ap.add_argument("--init", action="store_true",
                    help="create the ledger with its header if it is absent, "
                         "then exit. The ONLY thing that creates it.")
    ap.add_argument("--rate-limits", metavar="CONFIG_DIR", action="append",
                    help="read a token agent's rate-limit snapshot from its Claude "
                         "config dir (%s, written by usage_statusline.py) instead "
                         "of a captured /usage screen; repeat it for every holder of "
                         "a shared account, and the freshest snapshot is read"
                         % SNAPSHOT_NAME)
    ap.add_argument("--now", type=float, default=None,
                    help="override the clock, epoch seconds (tests)")
    args = ap.parse_args(argv)

    now_epoch = args.now if args.now is not None else datetime.now(
        tz=timezone.utc).timestamp()
    if args.rate_limits and args.capture:
        sys.stderr.write("--rate-limits replaces the capture; give one or the other\n")
        return 2

    if args.init:
        if not args.ledger:
            sys.stderr.write("--init needs --ledger <path>\n")
            return 2
        if os.path.exists(args.ledger):
            sys.stderr.write("ledger already exists: %s\n" % args.ledger)
            return 0
        with open(args.ledger, "w", encoding="utf-8") as fh:
            fh.write(LEDGER_PREAMBLE)
        sys.stderr.write("created %s\n" % args.ledger)
        return 0

    # ⚠️ A LEDGER IS REQUIRED UNLESS FLOOR-ONLY IS ASKED FOR EXPLICITLY.
    # A forgotten `--ledger` would otherwise give a floor-only reading that
    # reports `ok` and exits 0 - indistinguishable from a fully projected clean
    # sweep, and the same "green for ever while measuring nothing" outcome the
    # missing-ledger refusal exists to prevent, reached through the front door.
    # So a degraded reading has to be requested.
    if not args.ledger and not args.floor_only:
        sys.stderr.write(
            "no --ledger: refusing to issue a floor-only reading that nobody "
            "asked for.\nWithout a ledger there is no previous row, so no "
            "velocity, no projection, and only the absolute floor is applied - "
            "a smaller claim than `ok`, and it must not be reported as one. "
            "Pass --ledger <agents.md> --agent <name> --account <acct>, or say "
            "--floor-only if that really is what you want.\n")
        return 2
    if args.ledger and args.floor_only:
        sys.stderr.write("--floor-only and --ledger are mutually exclusive\n")
        return 2
    if args.ledger and not args.agent:
        sys.stderr.write("--ledger needs --agent <name>: the rows are per "
                         "agent and there is nothing to read without one\n")
        return 2
    if args.ledger and not args.account:
        sys.stderr.write(
            "--ledger needs --account <acct>: the previous row is matched on "
            "the window AND the account, so an omitted account matches nothing "
            "and every window reads as a first reading - on every sweep, for "
            "ever, at exit 0. `tmux_triage.sh <agent> --current-account` "
            "answers it with no keystrokes.\n")
        return 2
    if args.append and not args.ledger:
        sys.stderr.write("--append needs --ledger <path>\n")
        return 2

    account = args.account or "-"
    lock = None
    rows = None
    if args.ledger:
        if not os.path.exists(args.ledger):
            # Deliberately NOT a first reading. See the module docstring.
            sys.stderr.write(
                "ledger not found: %s\n"
                "This is an instrument fault, not an agent with no history: a "
                "mistyped path reads as 'first reading' forever and the sweep "
                "never acts on anything. Create it once with --init.\n"
                % args.ledger)
            return 2
        # ⚠️ THE LOCK IS TAKEN BEFORE THE READ, NOT BEFORE THE WRITE. The append
        # is a read-modify-write, so locking only the write still lets a
        # concurrent sweep's row land between this one's read and its write, and
        # the row is then lost.
        if args.append:
            lock = lock_ledger(args.ledger)
        rows = read_ledger_rows(args.ledger, args.agent)

    limits, no_limits = None, None
    text = ""
    if args.rate_limits:
        try:
            limits, no_limits = read_snapshot(args.rate_limits, now_epoch)
        except SnapshotError as exc:
            sys.stderr.write("SNAPSHOT FAULT: %s\n" % exc)
            return 2
    else:
        try:
            if args.capture:
                with open(args.capture, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            else:
                text = sys.stdin.read()
        except OSError as exc:
            sys.stderr.write("cannot read the capture: %s\n" % exc)
            return 2

    result = analyse(text, now_epoch, rows=rows, account=account,
                     have_ledger=bool(args.ledger), limits=limits,
                     no_limits_reason=no_limits or None)
    result["agent"] = args.agent
    result["account"] = account
    result["now"] = datetime.fromtimestamp(
        now_epoch, tz=timezone.utc).strftime(TIME_FMT)
    result["ledger"] = {
        "path": args.ledger,
        "rows_read": None if rows is None else len(rows),
        # null = no append was ATTEMPTED; an integer = one was, and this is how
        # many rows it wrote. The two are kept apart so that "the inconclusive
        # guard is in place" is observable from the outside: without the guard
        # an inconclusive capture reports 0 here rather than null, because it
        # would attempt an append of its (empty) limit list. A test that only
        # compared the ledger's bytes could not tell those apart, since an
        # append of zero rows changes nothing - and a guard nothing can see is
        # a guard the next tidy-up deletes.
        "rows_appended": None,
    }

    if args.append and result["verdict"] != "inconclusive":
        new_rows = build_rows(result, now_epoch, account)
        append_rows(args.ledger, args.agent, new_rows)
        result["ledger"]["rows_appended"] = len(new_rows)

    if lock is not None:
        lock.close()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Exit status mirrors the verdict so a shell caller cannot silently read a
    # degraded state as ok: 0 = ok, 1 = trigger, 3 = inconclusive,
    # 4 = floor-only. 2 is the instrument fault, raised above and in the
    # wrapper below.
    return {"ok": 0, "trigger": 1, "inconclusive": 3, "floor-only": 4}[
        result["verdict"]]


def main_guarded(argv=None):
    """⚠️ ANY UNEXPECTED EXCEPTION IS EXIT 2, NEVER EXIT 1.

    Exit 1 is the published contract for `hand this agent over`, and an
    uncaught traceback exits 1 - so without this guard a `--ledger` pointing at
    a DIRECTORY, a `--init` into a missing directory, or any other unexpected
    exception reads to a caller as the loudest verdict this script has. An
    instrument that has fallen over must not pronounce on an agent at all.
    """
    try:
        return main(argv)
    except LedgerError as exc:
        sys.stderr.write("LEDGER FAULT: %s\n" % exc)
        return 2
    except OSError as exc:
        sys.stderr.write("INSTRUMENT FAULT (I/O): %s\n" % exc)
        return 2
    except Exception as exc:  # noqa: BLE001 - deliberate, see the docstring
        sys.stderr.write("INSTRUMENT FAULT (%s): %s\n"
                         % (type(exc).__name__, exc))
        return 2


if __name__ == "__main__":
    sys.exit(main_guarded())
