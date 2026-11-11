#!/usr/bin/env python3
"""Offline regression guard for claim.py - the fleet's claim rule.

Run: python3 claim.test.py   (from any directory; it anchors to its own path)

Hermetic: every case works in its own `tempfile` directory and passes `--dir`
(or calls the module with a directory argument), so the real claims directory
is never read or written, and nothing touches the network or any chat service.
The fleet settings it reads are the repository's fixtures: FLEET_HOST_CONFIG and
FLEET_CONTEXT_ROOT are set below to tests/fixtures/host.json and
tests/fixtures/install, as ABSOLUTE paths, whatever the caller exported - a
relative value would stop resolving in the cases that run the CLI from another
working directory, and a real host's settings would put the cases that omit
--dir in the live claims directory.

THREE OUTCOMES, never two - the last line says which:

    0  ALL CHECKS PASSED
    1  FAILED - a check found a defect
    3  NO VERDICT - a NEGATIVE CONTROL did not fire, or a control or a race it
       vouches for did not run (deleted, renamed, skipped), so the race results
       mean nothing, whichever way they came out

WHAT THE RACE TESTS CATCH, AS MEASURED, AND WHAT THEY DO NOT. Each requires,
per round, exactly one winner, every loser naming that winner, the file naming
the winner, and no temp file left behind.
  - The MODULE race (test_01a) runs RACERS racers for ROUNDS rounds from a SPIN
    GATE: the parent releases a round only when every racer is busy-waiting on
    a shared value, so they leave within microseconds. It catches a check-then-
    write take with NO widening sleep - exists(), then open-for-write, the gap
    between them only the natural few microseconds: measured 2026-11-01 on a
    32-core host with 40 racers x 12 rounds, that mutant applied to claim.py's
    take was caught by this test in 20 of 20 runs. (A multiprocessing Barrier,
    which wakes its parties one at a time over milliseconds, caught it in 0 of
    20.)
  - THE HARNESS IS SIZED TO THE CPUs THIS PROCESS MAY USE (see RACERS below).
    On fewer than 8, racers outnumber the cores, the gate's release spread grows
    to milliseconds, and a round overlaps only sometimes: measured 2026-11-06,
    40 racers on 2 CPUs saw the no-widening mutant in about one round in seven,
    and the fleet's CI runner saw it in 0 of 12 rounds on one run and passed on
    the next - a gate that disagreed with itself on identical code. So a small
    machine runs 2 racers per CPU for 120 rounds: on 2 CPUs, 40 to 83 of the 120
    rounds overlapped across three runs, and on 4 CPUs 119 and 120. One usable
    CPU skips the no-widening control, so that run is NO VERDICT. The
    real race and its controls read the same RACERS and ROUNDS, so a control that
    fires vouches for exactly the harness the real race ran, never for a larger
    one.
  - The CLI race (test_01b) is one round of 12 real interpreters behind a file
    gate. It exists for the real entry point, not for window resolution: each
    racer pays an interpreter start, and it caught the same mutant in 16 of
    40 runs.
  - The TAKEOVER race (test_04a) is TAKEOVER_RACERS racers x ROUNDS rounds
    through the same gate.
  - None of them can see a window narrower than the gate's release spread, and
    none measures link(2)'s atomicity, which is the kernel's guarantee.

⚠️ THE NEGATIVE CONTROLS ARE WHY A GREEN RACE MEANS ANYTHING, AND DELETING
THEM LEAVES THE RACE TESTS GREEN FOREVER. A harness whose racers never overlap
reports exactly one winner for ANY take, correct or broken. So each harness is
also run against a deliberately NAIVE take defined in THIS file and never in
claim.py, and must see MORE than one winner: the module harness with a widening
sleep (every round) AND with none (at least one round - this is the control
that keeps the claim above true; it is skipped, and the run is NO VERDICT, on a
one-CPU machine, where no two racers can overlap), the CLI harness with a
sleep. ⚠️ IF A CONTROL PASSES (one winner against a naive take) OR DID NOT RUN,
THE RUN ISSUES NO VERDICT: exit 3, not 0 - REQUIRED at the bottom of this file
names them. A control can only void a GREEN: a race that found two winners
against the real take is a real defect whatever the controls did, so that is
still exit 1.

POSITIVE EVIDENCE THAT THE SUBJECT WAS REACHED: every race verdict first
requires a result from EVERY racer. A racer that died before reaching the take
(a broken barrier, a spawn failure, an import error in the child) is a
violation, never an absent loser.
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import io
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPT = os.path.join(HERE, "claim.py")
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "tests", "fixtures")
os.environ["FLEET_HOST_CONFIG"] = os.path.join(FIXTURES, "host.json")
os.environ["FLEET_CONTEXT_ROOT"] = os.path.join(FIXTURES, "install")
# The registry under test is this tree's own transports: FLEET_TRANSPORTS_DIR (a
# fleetlib test seam) would swap in a fixture registry with other transports.
os.environ.pop("FLEET_TRANSPORTS_DIR", None)
# ⚠️ HOME IS A THROWAWAY DIRECTORY for this whole file, in-process and in every
# child. On a fleet host the live claims directory sits under the real home
# (`~/agents/claims`), and so does the real host.json (~/.config/agent-fleet/), so a
# claim.py with the defects these cases look for - expanding `$HOME` in claims_dir,
# or reading the default host.json past FLEET_HOST_CONFIG - would take its claims in
# the live directory, where real agents' requests are decided. Under this HOME such
# a defect reds the case and touches nothing. Removing it makes the suite unsafe to
# run exactly when it is finding something.
# The race harness's spawned children re-run this module's top level; they inherit
# the parent's TEST_HOME through the environment instead of each making one.
TEST_HOME = os.environ.get("CLAIM_TEST_HOME") or tempfile.mkdtemp(prefix="claim-test-home-")
os.environ["CLAIM_TEST_HOME"] = os.environ["HOME"] = TEST_HOME


def _load_claim():
    spec = importlib.util.spec_from_file_location("fleet_claim", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


claim = _load_claim()
try:
    SLACK = claim.transport("slack")
    SLACK_ERROR = None
except Exception as _e:  # noqa: BLE001 - reported by main() as a FAILURE, never swallowed
    SLACK, SLACK_ERROR = None, f"{type(_e).__name__}: {_e}"

CH = "C0EXAMPLE01"
TS = "1700000000.123456"
# A Slack claim's name in the Slack-only version's format, WRITTEN OUT: built
# with the function under test it would agree with any change to that function.
SLACK_NAME = "C0EXAMPLE01-1700000000.000001"
# Sized to the CPUs this process may run on - its affinity, not the machine's
# count, because a CI runner or a taskset slice is smaller than the host. Why the
# two sizes, and what each was measured to catch: the module docstring.
CPUS = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
_LARGE = CPUS >= 8
RACERS = 40 if _LARGE else max(2, 2 * CPUS)   # module-level race: workers released from a spin gate
ROUNDS = 12 if _LARGE else 120                # module-level races run this many rounds, each on a fresh claim
TAKEOVER_RACERS = 24 if _LARGE else RACERS
CLI_RACERS = 12       # CLI-level race: real interpreter processes behind a file gate
NAIVE_WINDOW_SECS = 0.05      # module control: racers leave the spin gate within microseconds
CLI_NAIVE_WINDOW_SECS = 0.3   # CLI control: each racer still pays an interpreter start
DAY = 86400


def round_ts(r):
    return f"{1700000000 + r}.123456"


# --- the race harness (module level, so spawned children can import it) ----

def _naive_take(d, channel, ts, agent, window):
    """THE NEGATIVE CONTROLS' SUBJECT - deliberately WRONG, never imported by
    claim.py: exists-check, then open-for-write. With WINDOW > 0 a sleep widens
    the gap between the two; with WINDOW == 0 the gap is only the natural few
    microseconds between two syscalls, which is the mutant a harness must catch."""
    final = os.path.join(d, f"{channel}-{ts}")
    if os.path.exists(final):
        with open(final) as f:
            owner = (re.search(r"^agent: (\S+)", f.read(), re.M) or [None, "?"])[1]
        return 1, f"CLAIMED-BY {owner} at ?"
    if window:
        time.sleep(window)
    with open(final, "w") as f:
        f.write(f"agent: {agent}\nclaimed: {claim.utc_now()}\n")
    return 0, f"CLAIMED {final} by {agent} at ?"


def _race_worker(kind, d, agent, rounds, window, from_, ready, go, q):
    """One racer for every round. Per round: announce readiness, BUSY-WAIT on the
    shared release value, then take. A Barrier wakes its parties one at a time
    over milliseconds, which is wider than a check-then-write window; a spin gate
    releases every running racer within microseconds."""
    rows = []
    try:
        for r in range(1, rounds + 1):
            ts = round_ts(r)
            with ready.get_lock():
                ready.value += 1
            spins, deadline = 0, time.monotonic() + 120
            while go.value < r:
                spins += 1
                if not spins & 0x3FFF and time.monotonic() > deadline:
                    raise TimeoutError(f"round {r} was never released")
            t0 = time.monotonic()
            if kind == "take":
                res = claim.take(d, SLACK, CH, ts, agent)
                code, line = res.code, res.line
            elif kind == "takeover":
                res = claim.takeover(d, SLACK, CH, ts, agent, from_)
                code, line = res.code, res.line
            else:
                code, line = _naive_take(d, CH, ts, agent, window)
            rows.append((r, agent, code, line, t0, None))
    except BaseException as e:  # noqa: BLE001 - reported, never swallowed
        rows.append((None, agent, None, None, None, f"{type(e).__name__}: {e}"))
    q.put(rows)


def run_race(kind, d, agents, rounds=ROUNDS, window=0.0, from_=None):
    """-> ({round: [(agent, code, line, released_at, error)]}, [error rows]).
    The parent releases round r only once EVERY racer has announced it, so all
    of them are spinning when the release lands."""
    ctx = mp.get_context("spawn")
    ready, go, q = ctx.Value("i", 0), ctx.RawValue("i", 0), ctx.Queue()
    procs = [ctx.Process(target=_race_worker,
                         args=(kind, d, a, rounds, window, from_, ready, go, q)) for a in agents]
    for p in procs:
        p.start()
    n = len(agents)
    for r in range(1, rounds + 1):
        deadline = time.monotonic() + (120 if r == 1 else 60)
        while ready.value < n * r and time.monotonic() < deadline \
                and all(p.is_alive() for p in procs):
            time.sleep(0.0002)
        if ready.value < n * r:
            go.value = rounds + 1  # a racer is gone: let the rest finish, the verdict reports it
            break
        go.value = r
    reports = []
    try:
        for _ in agents:
            reports.extend(q.get(timeout=120))
    except Exception:  # noqa: BLE001 - a missing report is a violation in the verdict
        pass
    for p in procs:
        p.join(timeout=30)
        if p.is_alive():
            p.kill()
    by_round = {r: [row[1:] for row in reports if row[0] == r] for r in range(1, rounds + 1)}
    return by_round, [row for row in reports if row[0] is None]


def rounds_verdict(d, by_round, errors, n):
    """-> (violations, winners per round). Every round must pass race_verdict."""
    v = [f"racer error: {e[5]}" for e in errors[:3]]
    counts = []
    for r, rows in sorted(by_round.items()):
        rv, winners = race_verdict(d, rows, n, os.path.join(d, f"{CH}-{round_ts(r)}"))
        counts.append(len(winners))
        v += [f"round {r}: {x}" for x in rv]
    return v, counts


def round_spread_us(by_round):
    """Median over rounds of the gap between the first and last racer leaving the gate."""
    gaps = sorted((max(t) - min(t)) * 1e6 for t in
                  ([row[3] for row in rows if row[3] is not None] for rows in by_round.values()) if t)
    return gaps[len(gaps) // 2] if gaps else float("nan")


_GATE_WRAPPER = r"""
import os, sys, time
ready, gate = sys.argv[1], sys.argv[2]
open(os.path.join(ready, str(os.getpid())), "w").close()
deadline = time.monotonic() + 60
while not os.path.exists(gate):
    if time.monotonic() > deadline:
        sys.exit(97)
    time.sleep(0.0005)
os.execv(sys.executable, [sys.executable] + sys.argv[3:])
"""


def run_cli_race(script, d, agents, work):
    """The CLI-level race: each racer is a real interpreter that waits at a
    file gate and then exec()s `python3 <script> take ...`, so what races is the
    real entry point, argument parsing and all."""
    ready = os.path.join(work, "ready")
    gate = os.path.join(work, "gate")
    os.mkdir(ready)
    procs = [(a, subprocess.Popen(
        [sys.executable, "-c", _GATE_WRAPPER, ready, gate, script,
         "take", CH, TS, "--agent", a, "--dir", d],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)) for a in agents]
    deadline = time.monotonic() + 60
    while len(os.listdir(ready)) < len(agents) and time.monotonic() < deadline:
        time.sleep(0.005)
    open(gate, "w").close()
    rows = []
    for a, p in procs:
        out, err = p.communicate(timeout=60)
        rows.append((a, p.returncode, out.strip(), None, err.strip() or None))
    return rows


def race_verdict(d, rows, n, final):
    """-> (violations, winners). The same verdict for the real take and for the
    naive control, so the control measures THIS function too."""
    v = []
    if len(rows) != n:
        v.append(f"only {len(rows)} of {n} racers reported a result")
    errs = [r for r in rows if r[4]]
    if errs:
        v.append(f"{len(errs)} racer(s) errored: {errs[:3]}")
    winners = [r for r in rows if r[1] == 0]
    if len(winners) != 1:
        v.append(f"{len(winners)} winners: {[r[0] for r in winners][:10]}")
    else:
        w = winners[0][0]
        bad = [r for r in rows if r[1] != 0 and not (r[2] or "").startswith(f"CLAIMED-BY {w} ")]
        if bad:
            v.append(f"{len(bad)} loser(s) did not name the winner {w}: {bad[:3]}")
        rec = claim.read_claim(final)
        if rec is None or rec["agent"] != w:
            v.append(f"the claim file names {rec and rec['agent']!r}, the winner was {w!r}")
    tmps = [f for f in os.listdir(d) if f.endswith(".tmp")]
    if tmps:
        v.append(f"temp files left behind: {tmps}")
    return v, winners


# --- helpers -----------------------------------------------------------------

def cli(*args, cwd=None, env=None, timeout=60, script=SCRIPT):
    r = subprocess.run([sys.executable, script, *args], capture_output=True, text=True,
                       cwd=cwd, env=env, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def age(path, secs, follow=True):
    t = time.time() - secs
    os.utime(path, (t, t), follow_symlinks=follow)


def listing(path):
    out = []
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            out.append(os.path.relpath(os.path.join(root, name), path))
    return sorted(out)


NAIVE_CLI = r"""
import os, sys, time
_, verb, channel, ts, _a, agent, _d, d = sys.argv
final = os.path.join(d, f"{channel}-{ts}")
if os.path.exists(final):
    print("CLAIMED-BY someone at ?"); sys.exit(1)
time.sleep(%r)
with open(final, "w") as f:
    f.write(f"agent: {agent}\nclaimed: x\n")
print(f"CLAIMED {final} by {agent} at ?")
""" % CLI_NAIVE_WINDOW_SECS


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="claim-test-")
        self.root = self._tmp.name
        self.d = os.path.join(self.root, "claims")
        os.mkdir(self.d, 0o700)
        self.final = os.path.join(self.d, f"{CH}-{TS}")

    def tearDown(self):
        for root, dirs, _ in os.walk(self.root):
            for x in dirs:
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(root, x), 0o700)
        self._tmp.cleanup()

    # 1. THE RACE ------------------------------------------------------------
    def test_01a_race_module_exactly_one_winner(self):
        by_round, errors = run_race("take", self.d, [f"racer{i:02d}" for i in range(RACERS)])
        v, counts = rounds_verdict(self.d, by_round, errors, RACERS)
        print(f"    race(module, real take): {RACERS} racers x {ROUNDS} rounds, winners per round "
              f"{counts}, median release spread {round_spread_us(by_round):.0f} us")
        self.assertEqual(v, [])
        self.assertEqual(len(os.listdir(self.d)), ROUNDS, "one claim file per round and nothing else")

    def test_01b_race_cli_exactly_one_winner(self):
        work = os.path.join(self.root, "work")
        os.mkdir(work)
        rows = run_cli_race(SCRIPT, self.d, [f"cli{i:02d}" for i in range(CLI_RACERS)], work)
        v, winners = race_verdict(self.d, rows, CLI_RACERS, self.final)
        print(f"    race(CLI, real take): {len(rows)}/{CLI_RACERS} reported, {len(winners)} winner(s) "
              f"{[w[0] for w in winners]}, exit codes {sorted(r[1] for r in rows)}")
        self.assertEqual(v, [])
        self.assertEqual(sorted(r[1] for r in rows), [0] + [1] * (CLI_RACERS - 1))

    # 2. NEGATIVE CONTROLS: the same harnesses must SEE a broken take -------------
    def test_02a_negative_control_module_naive_take_has_many_winners(self):
        by_round, errors = run_race("naive", self.d, [f"naive{i:02d}" for i in range(RACERS)],
                                    window=NAIVE_WINDOW_SECS)
        v, counts = rounds_verdict(self.d, by_round, errors, RACERS)
        print(f"    CONTROL race(module, NAIVE take, {NAIVE_WINDOW_SECS}s window): winners per round "
              f"{counts}, median release spread {round_spread_us(by_round):.0f} us")
        self.assertEqual(errors, [], "the control's racers did not all run")
        self.assertTrue(all(c > 1 for c in counts) and len(counts) == ROUNDS,
                        "a round of the race harness could not see a widened check-then-write")

    @unittest.skipIf(CPUS < 2, "one CPU cannot run two racers at once")
    def test_02c_negative_control_module_naive_take_without_widening(self):
        """THE CONTROL THAT SAYS WHAT THE MODULE RACE CATCHES: a check-then-write
        with NO sleep - only the natural gap between exists() and open() - must
        produce a second winner in at least one round. Skipped (and so NO VERDICT)
        on a one-CPU machine, where no two racers can overlap at all."""
        by_round, errors = run_race("naive", self.d, [f"bare{i:02d}" for i in range(RACERS)])
        v, counts = rounds_verdict(self.d, by_round, errors, RACERS)
        print(f"    CONTROL race(module, NAIVE take, no window): winners per round {counts}, "
              f"rounds with a double winner {sum(c > 1 for c in counts)}/{ROUNDS}")
        self.assertEqual(errors, [], "the control's racers did not all run")
        self.assertTrue(any(c > 1 for c in counts),
                        "the race harness could not see a check-then-write with no widening")

    def test_02b_negative_control_cli_naive_take_has_many_winners(self):
        work = os.path.join(self.root, "work")
        os.mkdir(work)
        naive = os.path.join(work, "naive_claim.py")
        with open(naive, "w") as f:
            f.write(NAIVE_CLI)
        rows = run_cli_race(naive, self.d, [f"naive{i:02d}" for i in range(CLI_RACERS)], work)
        v, winners = race_verdict(self.d, rows, CLI_RACERS, self.final)
        print(f"    CONTROL race(CLI, NAIVE take): {len(rows)}/{CLI_RACERS} reported, "
              f"{len(winners)} winner(s), violations: {v[:2]}")
        self.assertEqual(len(rows), CLI_RACERS, "the control's racers did not all report")
        self.assertGreater(len(winners), 1, "the CLI race harness could not see a check-then-write take")

    # 3. RE-TAKE, SHOW, RELEASE ----------------------------------------------------
    def test_03a_owner_retake_is_already_yours_and_changes_nothing(self):
        self.assertEqual(cli("take", CH, TS, "--agent", "ada", "--dir", self.d)[0], 0)
        before = open(self.final, "rb").read()
        rc, out, err = cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith(f"ALREADY-YOURS {self.final} by ada at "), out)
        self.assertEqual(open(self.final, "rb").read(), before)
        rc, out, _ = cli("take", CH, TS, "--agent", "grace", "--dir", self.d)
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)
        self.assertEqual(open(self.final, "rb").read(), before)

    def test_03e_owner_retake_survives_its_own_lazy_prune(self):
        """Prune judges age by mtime, so an ALREADY-YOURS that left the mtime
        alone let the same take's lazy prune delete the claim it had just
        confirmed - and the next agent then won the request."""
        days = claim.RETENTION_DAYS
        self.assertEqual(cli("take", CH, TS, "--agent", "ada", "--dir", self.d)[0], 0)
        age(self.final, (days + 0.5) * DAY)
        open(os.path.join(self.d, ".last-prune"), "w").close()
        age(os.path.join(self.d, ".last-prune"), 25 * 3600)
        rc, out, err = cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.startswith("ALREADY-YOURS "), out)
        self.assertTrue(os.path.lexists(self.final), "the lazy prune deleted the claim take just confirmed")
        rc, out, _ = cli("take", CH, TS, "--agent", "grace", "--dir", self.d)
        self.assertEqual(rc, 1, out)
        self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)

    def test_03b_claim_file_format(self):
        rc, out, _ = cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual(rc, 0)
        text = open(self.final).read()
        self.assertRegex(text, r"\Aagent: ada\nclaimed: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n\Z")
        self.assertRegex(out, rf"\ACLAIMED {re.escape(self.final)} by ada at \S+Z\Z")

    def test_03c_show_claimed_and_unclaimed(self):
        self.assertEqual(cli("show", CH, TS, "--dir", self.d)[:2], (1, "UNCLAIMED"))
        cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        rc, out, _ = cli("show", CH, TS, "--dir", self.d)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)

    def test_03d_release_by_owner_non_owner_and_unclaimed(self):
        self.assertEqual(cli("release", CH, TS, "--agent", "ada", "--dir", self.d)[:2],
                         (1, "UNCLAIMED"))
        cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        before = open(self.final, "rb").read()
        rc, out, _ = cli("release", CH, TS, "--agent", "grace", "--dir", self.d)
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)
        self.assertEqual(open(self.final, "rb").read(), before)
        rc, out, _ = cli("release", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.lexists(self.final))
        self.assertEqual(cli("take", CH, TS, "--agent", "grace", "--dir", self.d)[0], 0,
                         "a released request must be takeable again")

    # 3f. CLAIM NAMES, per transport ---------------------------------------------------
    def test_03f_claim_names_per_transport(self):
        """A Slack claim name is byte-identical to the Slack-only version's, which is
        what lets the two versions share one claim space while agents move between
        them (test_09 measures that against a real previous version). Every other
        transport's name carries `<transport>--`. The expected names are written out
        here, never built with the function under test."""
        for argv, name in (
                (["take", CH, "1700000000.000001", "--agent", "ada"],
                 SLACK_NAME),
                (["take", CH, "1700000000.000002", "--agent", "ada", "--transport", "slack"],
                 CH + "-1700000000.000002"),
                (["take", "123456789012345678", "234567890123456789", "--agent", "ada",
                  "--transport", "discord"],
                 "discord--123456789012345678-234567890123456789"),
                (["take", "-1001234567", "42", "--agent", "ada", "--transport", "telegram"],
                 "telegram---1001234567-42")):
            with self.subTest(argv=argv):
                rc, out, err = cli(*argv, "--dir", self.d)
                self.assertEqual(rc, 0, (out, err))
                self.assertEqual(out.split(" ")[1], os.path.join(self.d, name), out)
                self.assertTrue(os.path.isfile(os.path.join(self.d, name)))
        self.assertEqual(sorted(f for f in os.listdir(self.d) if not f.startswith(".")),
                         sorted([SLACK_NAME, CH + "-1700000000.000002",
                                 "discord--123456789012345678-234567890123456789",
                                 "telegram---1001234567-42"]))

    def test_03g_ids_are_validated_per_transport(self):
        """Each transport's ids are checked against ITS descriptor: a Slack id is not
        a Discord id, an unknown transport is bad input, and both are exit 2 with
        nothing written."""
        cwd = os.path.join(self.root, "cwd")
        os.mkdir(cwd)
        for argv in (["take", CH, TS, "--agent", "ada", "--transport", "discord"],
                     ["take", "123456789012345678", "234567890123456789", "--agent", "ada"],
                     ["take", CH, TS, "--agent", "ada", "--transport", "nosuch"],
                     ["show", "-1001234567", "4.2", "--transport", "telegram"]):
            with self.subTest(argv=argv):
                self._refused(2, *argv, "--dir", self.d, cwd=cwd)

    # 4. TAKEOVER -------------------------------------------------------------------
    def test_04a_takeover_race_exactly_one_winner(self):
        originals = {}
        for r in range(1, ROUNDS + 1):
            self.assertEqual(claim.take(self.d, SLACK, CH, round_ts(r), "owner").code, 0)
            originals[r] = claim.read_claim(os.path.join(self.d, f"{CH}-{round_ts(r)}"))["claimed"]
        by_round, errors = run_race("takeover", self.d, [f"taker{i:02d}" for i in range(TAKEOVER_RACERS)],
                                    from_="owner")
        v, counts = rounds_verdict(self.d, by_round, errors, TAKEOVER_RACERS)
        print(f"    takeover race: {TAKEOVER_RACERS} racers x {ROUNDS} rounds, winners per round {counts}")
        self.assertEqual(v, [])
        for r in range(1, ROUNDS + 1):
            rec = claim.read_claim(os.path.join(self.d, f"{CH}-{round_ts(r)}"))
            self.assertEqual((rec["took_over_from"], rec["original_claim"]), ("owner", originals[r]))

    def test_04b_takeover_wrong_from_is_refused_byte_identical(self):
        cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        before = open(self.final, "rb").read()
        rc, out, _ = cli("takeover", CH, TS, "--agent", "alan", "--from", "grace", "--dir", self.d)
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)
        self.assertEqual(open(self.final, "rb").read(), before)

    def test_04c_takeover_unclaimed_and_self(self):
        self.assertEqual(cli("takeover", CH, TS, "--agent", "alan", "--from", "grace",
                             "--dir", self.d)[:2], (1, "UNCLAIMED"))
        self.assertEqual(os.listdir(self.d), [".lock"])  # the lock, and no claim
        cli("take", CH, TS, "--agent", "alan", "--dir", self.d)
        before = open(self.final, "rb").read()
        self.assertEqual(cli("takeover", CH, TS, "--agent", "alan", "--from", "alan",
                             "--dir", self.d)[0], 2)
        self.assertEqual(open(self.final, "rb").read(), before)

    def test_04d_takeover_cli_records_the_chain(self):
        cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        original = claim.read_claim(self.final)["claimed"]
        rc, out, _ = cli("takeover", CH, TS, "--agent", "alan", "--from", "ada", "--dir", self.d)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.startswith(f"TOOK-OVER {self.final} by alan from ada at "), out)
        rec = claim.read_claim(self.final)
        self.assertEqual((rec["agent"], rec["took_over_from"], rec["original_claim"]),
                         ("alan", "ada", original))
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith(".tmp")], [])

    def test_04e_takeover_chain_keeps_the_first_claim_time(self):
        """ada -> grace -> alan: original_claim stays ada's time, not grace's."""
        first = "2026-01-01T00:00:00Z"
        with open(self.final, "w") as f:
            f.write(f"agent: ada\nclaimed: {first}\n")
        self.assertEqual(cli("takeover", CH, TS, "--agent", "grace", "--from", "ada",
                             "--dir", self.d)[0], 0)
        self.assertEqual(cli("takeover", CH, TS, "--agent", "alan", "--from", "grace",
                             "--dir", self.d)[0], 0)
        rec = claim.read_claim(self.final)
        self.assertEqual((rec["agent"], rec["took_over_from"], rec["original_claim"]),
                         ("alan", "grace", first))

    # 5. PRUNE ----------------------------------------------------------------------
    def test_05_prune_deletes_only_old_regular_claims_and_old_tmps(self):
        d = self.d
        old_claim = os.path.join(d, "C0OLD-1600000000.000001")
        young_claim = os.path.join(d, "C0YOUNG-1600000000.000002")
        not_a_claim = os.path.join(d, "notes.txt")
        near_miss = os.path.join(d, "C0OLD-1600000000.000001.bak")
        claim_dir = os.path.join(d, "C0DIR-1600000000.000003")
        nested = os.path.join(claim_dir, "C0NEST-1600000000.000004")
        outside = os.path.join(self.root, "outside")
        os.mkdir(outside)
        victim = os.path.join(outside, "victim")
        link = os.path.join(d, "C0LINK-1600000000.000005")
        # The temp files come from claim.py's OWN writer, never a hand-made name: a
        # change to its naming that prune's pattern no longer matches must red here.
        old_tmp = claim._write_tmp(d, "C0OLD-1600000000.000001", "ada", b"x")
        young_tmp = claim._write_tmp(d, "C0OLD-1600000000.000001", "grace", b"x")
        # Another transport's claims are claims too, in their own name form...
        old_discord = os.path.join(d, "discord--123456789012345678-234567890123456789")
        old_telegram = os.path.join(d, "telegram---1001234567-42")
        old_discord_tmp = claim._write_tmp(d, "discord--123456789012345678-234567890123456789",
                                           "ada", b"x")
        # ...and FOREIGN files that only look like one are never touched: a prefix no
        # transport owns, a transport's prefix around ids its descriptor refuses, and
        # a Slack claim written in the prefixed form Slack does not use.
        foreign = [os.path.join(d, n) for n in (
            "nosuch--123456789012345678-234567890123456789",
            "discord--C0OLD-1600000000.000001",
            "slack--C0OLD-1600000000.000001",
            "telegram--abc-42")]
        os.mkdir(claim_dir)
        for p in (old_claim, young_claim, not_a_claim, near_miss, nested, victim,
                  old_discord, old_telegram, *foreign):
            with open(p, "w") as f:
                f.write("agent: x\nclaimed: y\n")
        os.symlink(victim, link)
        for p in (old_claim, not_a_claim, near_miss, nested, victim, claim_dir,
                  old_discord, old_telegram, *foreign):
            age(p, 15 * DAY)
        age(link, 15 * DAY, follow=False)
        age(old_tmp, 2 * 3600)
        age(old_discord_tmp, 2 * 3600)
        rc, out, err = cli("prune", "--older-than", "14", "--dir", d)
        self.assertEqual((rc, out, err), (0, "PRUNED 5", ""))
        for p in (old_claim, old_tmp, old_discord, old_telegram, old_discord_tmp):
            self.assertFalse(os.path.lexists(p), f"prune kept {p}")
        for p in (young_claim, not_a_claim, near_miss, nested, link, young_tmp, *foreign):
            self.assertTrue(os.path.lexists(p), f"prune deleted {p}")
        self.assertTrue(os.path.exists(victim), "prune followed a symlink and deleted its target")

    # 6. LAZY PRUNE -----------------------------------------------------------------
    def _take_ok(self, ts, agent):
        rc, out, err = cli("take", CH, ts, "--agent", agent, "--dir", self.d)
        final = os.path.join(self.d, f"{CH}-{ts}")
        self.assertEqual(rc, 0, (out, err))
        self.assertRegex(out, rf"\ACLAIMED {re.escape(final)} by {agent} at \S+Z\Z")
        return err

    def _old_claim(self, ts, days):
        p = os.path.join(self.d, f"C0OLD-{ts}")
        with open(p, "w") as f:
            f.write("agent: x\nclaimed: y\n")
        age(p, (days + 2) * DAY)
        return p

    def test_06_lazy_prune_at_most_once_per_day_and_never_changes_take(self):
        days = claim.RETENTION_DAYS  # the one value the script prunes by
        stamp = os.path.join(self.d, ".last-prune")
        a = self._old_claim("1600000000.000001", days)
        self.assertEqual(self._take_ok("1700000001.000001", "lazy"), "")
        self.assertFalse(os.path.lexists(a), "no stamp: the first take must prune")
        self.assertTrue(os.path.isfile(stamp))
        c = self._old_claim("1600000000.000002", days)
        self._take_ok("1700000001.000002", "lazy")
        self.assertTrue(os.path.lexists(c), "a fresh stamp: a second take within 24 h must not prune")
        age(stamp, 25 * 3600)
        self._take_ok("1700000001.000003", "lazy")
        self.assertFalse(os.path.lexists(c), "a stamp older than 24 h: take must prune again")

        # Busy: another process holds the lock. take must neither block nor prune.
        age(stamp, 25 * 3600)
        f = self._old_claim("1600000000.000003", days)
        fd = os.open(os.path.join(self.d, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            t0 = time.monotonic()
            self.assertEqual(self._take_ok("1700000001.000004", "lazy"), "")
            self.assertLess(time.monotonic() - t0, 10, "take blocked behind the prune lock")
            self.assertTrue(os.path.lexists(f), "the prune ran although the lock was busy")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        # Failing: the lock path is a directory, so the prune cannot run at all.
        os.unlink(os.path.join(self.d, ".lock"))
        os.mkdir(os.path.join(self.d, ".lock"))
        err = self._take_ok("1700000001.000005", "lazy")
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("lazy prune skipped", err)
        self.assertEqual(claim.read_claim(os.path.join(self.d, f"{CH}-1700000001.000005"))["agent"],
                         "lazy")

    def test_06b_fifo_stamp_never_blocks_take(self):
        """A FIFO at .last-prune: opening it for write with no reader blocks
        forever unless the open is non-blocking. take must never block."""
        stamp = os.path.join(self.d, ".last-prune")
        os.mkfifo(stamp, 0o600)
        age(stamp, 25 * 3600)
        try:
            rc, out, err = cli("take", CH, TS, "--agent", "ada", "--dir", self.d, timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("take blocked on a FIFO at .last-prune")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.startswith(f"CLAIMED {self.final} by ada"), out)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("lazy prune skipped", err)

    def test_06c_a_future_stamp_is_stale(self):
        """A .last-prune dated in the future must not disable the lazy prune forever."""
        days = claim.RETENTION_DAYS
        stamp = os.path.join(self.d, ".last-prune")
        open(stamp, "w").close()
        age(stamp, -10 * DAY)
        old = self._old_claim("1600000000.000001", days)
        self._take_ok("1700000001.000001", "lazy")
        self.assertFalse(os.path.lexists(old), "a future-dated stamp suppressed the prune")
        self.assertLessEqual(os.lstat(stamp).st_mtime, time.time() + 1)

    def test_06d_a_fault_before_the_stamp_repeats_on_every_take(self):
        """Pins what the lazy prune's comment states: a fault BEFORE the stamp
        moves (here an unusable lock) is reported by every take, not once a day."""
        os.mkdir(os.path.join(self.d, ".lock"))
        for ts in ("1700000001.000001", "1700000001.000002"):
            err = self._take_ok(ts, "lazy")
            self.assertEqual(len(err.splitlines()), 1, err)
            self.assertIn("lazy prune skipped", err)

    # 7. INVALID INPUT, MISSING DIRECTORY, FAULTS -------------------------------------
    def _refused(self, want, *args, cwd):
        """Run the CLI; require exit WANT, nothing on stdout, and no file created
        anywhere under the test root or in the working directory. The listing is
        taken per case, so one refusal that DID write reds that case alone."""
        before = listing(self.root)
        rc, out, err = cli(*args, cwd=cwd)
        self.assertEqual(rc, want, (out, err))
        self.assertEqual(out, "", "a refusal must print nothing on stdout")
        self.assertEqual(listing(self.root), before, "a refusal created something")
        self.assertEqual(os.listdir(cwd), [])
        return err

    def test_07a_invalid_input_is_exit_2_and_writes_nothing(self):
        cwd = os.path.join(self.root, "cwd")
        os.mkdir(cwd)
        bad_channels = ["../x", "C1/../y", "", "c0lower", "C0ABC\n", "C0", "X0ABC"]
        bad_ts = ["../x", "", "123.45", "1700000000.123456\n", "1700000000.12345a"]
        bad_agents = ["Ada", "", "../x", "a/b", "a" * 33, "1abc", "ada\n"]
        cases = [["take", c, TS, "--agent", "ada"] for c in bad_channels] \
            + [["take", CH, t, "--agent", "ada"] for t in bad_ts] \
            + [["take", CH, TS, "--agent", a] for a in bad_agents] \
            + [["show", "../x", TS], ["release", CH, TS, "--agent", "../x"],
               ["release", "C1/../y", TS, "--agent", "a"]] \
            + [["takeover", CH, TS, "--agent", "alan", "--from", f] for f in ("../x", "Grace", "alan")] \
            + [["prune", "--older-than", n] for n in ("0", "-1", "nan", "inf")]
        for argv in cases:
            with self.subTest(argv=argv):
                self._refused(2, *argv, "--dir", self.d, cwd=cwd)
        with self.subTest(argv="relative --dir"):
            self._refused(2, "take", CH, TS, "--agent", "ada", "--dir", "claims", cwd=cwd)

    def test_07b_missing_or_wrong_dir_is_exit_3_and_creates_nothing(self):
        cwd = os.path.join(self.root, "cwd")
        os.mkdir(cwd)
        absent = os.path.join(self.root, "absent")
        a_file = os.path.join(self.root, "a-file")
        open(a_file, "w").close()
        for argv in (["take", CH, TS, "--agent", "ada"], ["show", CH, TS],
                     ["release", CH, TS, "--agent", "ada"],
                     ["takeover", CH, TS, "--agent", "alan", "--from", "ada"], ["prune"]):
            with self.subTest(argv=argv, dir="absent"):
                err = self._refused(3, *argv, "--dir", absent, cwd=cwd)
                self.assertEqual(err, f"NO CLAIMS DIR {absent} - `fleet install --agents-root {self.root}` creates it")
            with self.subTest(argv=argv, dir="a regular file"):
                self._refused(3, *argv, "--dir", a_file, cwd=cwd)
        self.assertFalse(os.path.lexists(absent))

    def test_07g_oversized_channel_or_ts_is_exit_2_not_3(self):
        """Unbounded patterns let a 230-character channel through validation and
        die in the filesystem (ENAMETOOLONG, exit 3). Slack's IDs and ts are short."""
        cwd = os.path.join(self.root, "cwd")
        os.mkdir(cwd)
        for argv in (["take", "C" + "A" * 229, TS, "--agent", "ada"],
                     ["take", CH, "1" * 30 + ".123456", "--agent", "ada"],
                     ["show", "C" + "A" * 229, TS]):
            with self.subTest(argv=argv[:2]):
                self._refused(2, *argv, "--dir", self.d, cwd=cwd)
        longest = "C" + "Z" * 20
        rc, out, err = cli("take", longest, "9999999999.999999", "--agent", "a" * 32, "--dir", self.d)
        self.assertEqual(rc, 0, err)

    def test_07h_exit_1_without_a_result_line_is_not_a_loss(self):
        """Exit 1 is also Python's own status for a script that could not run (a
        SyntaxError in a truncated or conflict-marked claim.py). The contract that
        separates them: every LOST/UNCLAIMED exit 1 carries its result line."""
        cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        other = f"{CH}-1700000009.000009"
        for argv, line in (
                (["take", CH, TS, "--agent", "grace"], "CLAIMED-BY ada at "),
                (["release", CH, TS, "--agent", "grace"], "CLAIMED-BY ada at "),
                (["takeover", CH, TS, "--agent", "alan", "--from", "grace"], "CLAIMED-BY ada at "),
                (["show", CH, "1700000009.000009"], "UNCLAIMED"),
                (["release", CH, "1700000009.000009", "--agent", "grace"], "UNCLAIMED"),
                (["takeover", CH, "1700000009.000009", "--agent", "alan", "--from", "grace"], "UNCLAIMED")):
            rc, out, _ = cli(*argv, "--dir", self.d)
            with self.subTest(argv=argv):
                self.assertEqual(rc, 1)
                self.assertEqual(len(out.splitlines()), 1, out)
                self.assertTrue(out.startswith(line), out)
        self.assertFalse(os.path.lexists(os.path.join(self.d, other)))
        # The confusable case, measured: a conflict-marked copy exits 1 with NO result line.
        broken = os.path.join(self.root, "claim.py")
        with open(SCRIPT) as f:
            src = f.read()
        with open(broken, "w") as f:
            f.write(src.replace("\ndef show(", "\n<<<<<<< HEAD\ndef show(", 1))
        rc, out, err = cli("take", CH, TS, "--agent", "grace", "--dir", self.d, script=broken)
        self.assertEqual((rc, out), (1, ""), err)
        self.assertIn("SyntaxError", err)
        # The rule is written where an agent reads it (this pins prose, not behaviour).
        with open(os.path.join(HERE, "SKILL.md")) as f:
            skill = f.read()
        start = skill.index("## Claiming a request")
        end = skill.find("\n## ", start + 1)
        section = skill[start:] if end == -1 else skill[start:end]
        for where, text in (("SKILL.md, Claiming a request", section), ("claim.py header", src)):
            with self.subTest(where=where):
                self.assertIn("with no `CLAIMED-BY` or `UNCLAIMED` line", text)

    @unittest.skipIf(os.geteuid() == 0, "root ignores the directory's mode bits")
    def test_07c_unwritable_dir_is_a_fault_never_a_loss(self):
        os.chmod(self.d, 0o500)
        rc, out, err = cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual((rc, out), (3, ""), err)
        self.assertIn("cannot be written", err)

    def test_07d_a_crash_exits_3_never_1(self):
        real = claim.take

        def boom(*a, **k):
            raise RuntimeError("synthetic crash")

        claim.take = boom
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = claim.main(["take", CH, TS, "--agent", "ada", "--dir", self.d])
        finally:
            claim.take = real
        self.assertEqual(rc, 3, "an uncaught exception would exit 1, which reads as LOST")
        self.assertIn("synthetic crash", err.getvalue())

    def test_07f_an_unwritable_result_line_exits_3_never_1(self):
        """A WIN whose line cannot be written (stdout a pipe with no reader) must
        not exit 1, which would make the agent that holds the claim stay out."""
        r_fd, w_fd = os.pipe()
        os.close(r_fd)
        try:
            p = subprocess.run([sys.executable, SCRIPT, "take", CH, TS, "--agent", "ada",
                                "--dir", self.d], stdout=w_fd, stderr=subprocess.PIPE, text=True,
                               timeout=60)
        finally:
            os.close(w_fd)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn(f"the outcome was: CLAIMED {self.final} by ada", p.stderr)
        self.assertEqual(claim.read_claim(self.final)["agent"], "ada")

    def test_07e_symlink_in_place_of_a_claim_is_a_fault(self):
        victim = os.path.join(self.root, "victim")
        with open(victim, "w") as f:
            f.write("agent: mallory\nclaimed: x\n")
        os.symlink(victim, self.final)
        for argv in (["take", CH, TS, "--agent", "ada"], ["show", CH, TS],
                     ["release", CH, TS, "--agent", "mallory"]):
            rc, out, _ = cli(*argv, "--dir", self.d)
            with self.subTest(argv=argv):
                self.assertEqual((rc, out), (3, ""))
        self.assertTrue(os.path.islink(self.final) and os.path.exists(victim))

    # 8. CONFIGURATION: one source, host.json's claims_dir ---------------------------
    def _host(self, **fields):
        """The fixture host settings with FIELDS over them (None drops a key),
        written to the test root; returns an env with that file selected."""
        with open(os.path.join(FIXTURES, "host.json")) as f:
            host = json.load(f)
        host.update(fields)
        p = os.path.join(self.root, "host.json")
        with open(p, "w") as f:
            json.dump({k: v for k, v in host.items() if v is not None}, f)
        return {**os.environ, "FLEET_HOST_CONFIG": p}

    def test_08_dir_comes_from_host_json_never_a_skill_config(self):
        """The claims directory is host.json's claims_dir: read from the fixture
        through the module, and end to end through the CLI with no --dir. A
        SLACK_WATCH_CONFIG or a slack-communication config naming another directory
        moves nothing - one source, or two claim spaces."""
        with open(os.environ["FLEET_HOST_CONFIG"]) as f:
            want = os.path.normpath(os.path.expanduser(json.load(f)["claims_dir"]))
        self.assertEqual(claim.configured_dir(), want, "the fixture host.json's claims_dir")
        decoy = os.path.join(self.root, "decoy")
        os.mkdir(decoy, 0o700)
        watch_cfg = os.path.join(self.root, "watch.json")
        with open(watch_cfg, "w") as f:
            json.dump({"claims": {"dir": decoy}}, f)
        env = {**self._host(claims_dir=self.d), "SLACK_WATCH_CONFIG": watch_cfg}
        rc, out, err = cli("take", CH, TS, "--agent", "ada", env=env)
        self.assertEqual(rc, 0, (out, err))
        self.assertTrue(os.path.isfile(self.final), "the claim did not land in host.json's claims_dir")
        self.assertEqual(os.listdir(decoy), [], "a skill or watcher config moved the claims directory")
        # --dir still wins over host.json: the tests' own seam.
        other = os.path.join(self.root, "other")
        os.mkdir(other, 0o700)
        rc, out, err = cli("take", CH, TS, "--agent", "grace", "--dir", other, env=env)
        self.assertEqual(rc, 0, (out, err))
        self.assertTrue(os.path.isfile(os.path.join(other, f"{CH}-{TS}")))

    def test_08b_host_claims_dir_is_validated(self):
        """`~` is the ONLY expansion (an environment variable would resolve per
        agent service), the result must be absolute, and a missing or unusable
        host.json is a 3 naming the cause - never a fallback directory."""
        # The REASON is asserted, not only the 3: an expander that resolved $HOME
        # would still exit 3 here, for a directory that merely does not exist.
        # HOME is this file's own temporary home (set at the top), so a claim.py
        # that DID expand $HOME reaches nothing real - see TEST_HOME.
        for raw in ("claims", "${HOME}/agents/claims", "$HOME/agents/claims"):
            with self.subTest(claims_dir=raw):
                rc, out, err = cli("take", CH, TS, "--agent", "ada", env=self._host(claims_dir=raw))
                self.assertEqual((rc, out), (3, ""), err)
                self.assertIn("does not resolve to an absolute path", err)
        for raw in ("", None):
            with self.subTest(claims_dir=raw):
                rc, out, err = cli("take", CH, TS, "--agent", "ada", env=self._host(claims_dir=raw))
                self.assertEqual((rc, out), (3, ""), err)
                self.assertIn("claims_dir", err)
        absent = {**os.environ, "FLEET_HOST_CONFIG": os.path.join(self.root, "no-such-host.json")}
        rc, out, err = cli("take", CH, TS, "--agent", "ada", env=absent)
        self.assertEqual((rc, out), (3, ""), err)
        self.assertIn("HOST SETTINGS", err)
        saved = os.environ["FLEET_HOST_CONFIG"]
        try:
            os.environ["FLEET_HOST_CONFIG"] = self._host(claims_dir="~/agents/claims")["FLEET_HOST_CONFIG"]
            self.assertEqual(claim.configured_dir(), os.path.expanduser("~/agents/claims"))
        finally:
            os.environ["FLEET_HOST_CONFIG"] = saved

    def test_08c_transport_defaults_to_the_install_default(self):
        """No --transport means the install manifest's transports.default (the
        fixture's is slack, whose names carry no prefix). With no manifest to read,
        the call is a 3 naming the missing default - never a guessed transport -
        and the same call with --transport still works."""
        rc, out, err = cli("take", CH, TS, "--agent", "ada", "--dir", self.d)
        self.assertEqual(rc, 0, (out, err))
        self.assertTrue(os.path.isfile(self.final), "the default transport did not name the claim as slack's")
        cwd = os.path.join(self.root, "cwd")
        os.mkdir(cwd)
        bare = {k: v for k, v in os.environ.items() if k not in ("FLEET_CONTEXT_ROOT", "CLAUDE_CONFIG_DIR")}
        rc, out, err = cli("show", CH, TS, "--dir", self.d, cwd=cwd, env=bare)
        self.assertEqual((rc, out), (3, ""), err)
        self.assertIn("NO DEFAULT TRANSPORT", err)
        rc, out, err = cli("show", CH, TS, "--transport", "slack", "--dir", self.d, cwd=cwd, env=bare)
        self.assertEqual((rc, out.startswith("CLAIMED-BY ada at ")), (0, True), (out, err))

    # 9. MIXED VERSIONS: the previous claim.py and this one share one claim space ----
    def test_09_mixed_versions_share_one_claim_space(self):
        """Run only when CLAIM_PREV_SCRIPT names the PREVIOUS version's claim.py (an
        export of the Slack-only script; it needs no config with --dir). A claim
        either version takes must read as CLAIMED-BY in the other, and neither may
        win it - the property that lets agents move to this version one at a time.
        Skipped otherwise: the previous version is not in this repository."""
        prev = os.environ.get("CLAIM_PREV_SCRIPT")
        if not prev:
            self.skipTest("set CLAIM_PREV_SCRIPT=<the previous version's claim.py> to run")
        self.assertTrue(os.path.isfile(prev), f"CLAIM_PREV_SCRIPT={prev} is not a file")
        for first, second in ((prev, SCRIPT), (SCRIPT, prev)):
            ts = "1700000000.000001" if first == prev else "1700000000.000002"
            with self.subTest(first=first):
                rc, out, err = cli("take", CH, ts, "--agent", "ada", "--dir", self.d, script=first)
                self.assertEqual(rc, 0, (out, err))
                self.assertEqual(out.split(" ")[1], os.path.join(self.d, f"{CH}-{ts}"), out)
                rc, out, err = cli("show", CH, ts, "--dir", self.d, script=second)
                self.assertEqual(rc, 0, (out, err))
                self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)
                rc, out, err = cli("take", CH, ts, "--agent", "grace", "--dir", self.d, script=second)
                self.assertEqual(rc, 1, (out, err))
                self.assertTrue(out.startswith("CLAIMED-BY ada at "), out)


# --- runner --------------------------------------------------------------------

# ⚠️ THE CONTROLS, AND THE RACES THEY VOUCH FOR, MUST HAVE RUN FOR A VERDICT TO
# EXIST. A runner that checks the controls only when they run and fail prints ALL
# CHECKS PASSED for a suite with both control tests deleted. So a
# control or a race that did not run to completion (deleted, renamed, skipped)
# makes the run NO VERDICT, exactly as a control that ran and did not fire does.
# Renaming one of these tests without renaming it here is a NO VERDICT on purpose.
CONTROLS = {"test_02a_negative_control_module_naive_take_has_many_winners",
            "test_02b_negative_control_cli_naive_take_has_many_winners",
            "test_02c_negative_control_module_naive_take_without_widening"}
RACES = {"test_01a_race_module_exactly_one_winner",
         "test_01b_race_cli_exactly_one_winner",
         "test_04a_takeover_race_exactly_one_winner"}
REQUIRED = CONTROLS | RACES


class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.ran = set()

    def startTest(self, test):
        super().startTest(test)
        self.ran.add(test._testMethodName)

    def addSuccess(self, test):
        super().addSuccess(test)
        print(f"[PASS] {test._testMethodName}", flush=True)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        print(f"[FAIL] {test._testMethodName} - {err[1]}", flush=True)

    def addError(self, test, err):
        super().addError(test, err)
        print(f"[FAIL] {test._testMethodName} - ERROR {err[0].__name__}: {err[1]}", flush=True)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            print(f"[FAIL] {subtest.id()} - {err[1]}", flush=True)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        print(f"[SKIP] {test._testMethodName} - {reason}", flush=True)


def main() -> int:
    if not os.path.isfile(SCRIPT):
        print(f"NO VERDICT: {SCRIPT} not found")
        return 3
    if SLACK_ERROR is not None:
        # The race harness and every module-level case need the slack transport; a
        # registry or fleetlib that cannot produce it is a defect claim.py ships with.
        print(f"FAILED: claim.transport('slack') raised {SLACK_ERROR}")
        return 1
    result = _Result()
    unittest.defaultTestLoader.loadTestsFromTestCase(ClaimTests).run(result)
    # A failed subTest is recorded as a _SubTest, whose test method name lives on
    # its parent case.
    failed = {getattr(t, "test_case", t)._testMethodName for t, _ in result.failures + result.errors}
    skipped = len(result.skipped)
    completed = result.ran - {t._testMethodName for t, _ in result.skipped}
    passed = result.testsRun - len(failed) - skipped
    print()
    # A FAILURE outside the controls is a finding whatever else happened, so it
    # wins; a missing or unfired control can only void a pass.
    if failed - CONTROLS:
        print(f"FAILED: {len(failed)} of {result.testsRun} test(s): {', '.join(sorted(failed))}")
        return 1
    if REQUIRED - completed:
        print(f"NO VERDICT: required control/race test(s) did not run: "
              f"{', '.join(sorted(REQUIRED - completed))} - without them a green race means nothing")
        return 3
    if failed & CONTROLS:
        print(f"NO VERDICT: negative control(s) {', '.join(sorted(failed & CONTROLS))} did not fire - "
              f"the race harness cannot see a broken take, so its green on the real one means nothing")
        return 3
    print(f"claim.test.py: {passed} passed, 0 failed, {skipped} skipped")
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        _rc = main()
    finally:
        shutil.rmtree(TEST_HOME, ignore_errors=True)
    sys.exit(_rc)
