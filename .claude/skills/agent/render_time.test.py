#!/usr/bin/env python3
"""Regression guard for render_time.py.

Offline and deterministic: every case hands the renderer a FIXED clock (an
explicit `now`, or `--now` on the command line) and three fixture reader
cities, so no assertion depends on when or where it runs.

WHY THESE THREE CITIES. Europe/Berlin observes daylight saving and
Asia/Kolkata does not and sits on a half-hour offset; Asia/Tokyo is a second
zone without daylight saving on a whole-hour offset. The same instant rendered
in January and in July must move Berlin's clock by one hour and leave Tokyo's
and Kolkata's alone: a renderer that applied a remembered offset instead of
the tz database passes every January case and fails only here, which is why
the July case exists. Kolkata's half hour catches a renderer that formats the
offset hour and drops the minutes. These are fixture values, chosen because
they belong to no install.

TWO LAYERS, AND THE SECOND ONE IS NOT DECORATIVE.
  1. The pure function, `render()`, imported from the script: every format
     rule (past, future, the hours-and-minutes form past an hour, the
     estimate wording, the within-the-minute wording, the clock format).
  2. The command line, run as a subprocess against a temporary install whose
     manifest is the fleet's fixture manifest with `house_rules.times.cities`
     replaced. Layer 1 cannot see WHERE the cities come from; this layer
     proves the script reads them from the install through fleetlib - two
     installs with different city lists give two different lines - and that
     with no install it refuses (exit 3) instead of falling back to a built-in
     city. Delete this layer and a script with the cities hard-coded passes.

A layer that cannot reach its subject FAILS, it never skips: the command-line
layer needs the fixture manifest, and when it is missing the run reports NO
VERDICT for that layer and exits 1, because a green earned without running the
command line would claim something nobody measured.

Run: python3 .claude/skills/agent/render_time.test.py
Exits nonzero on any failure.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPT = os.path.join(HERE, "render_time.py")
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
FIXTURE_HOST = os.path.join(FLEET_ROOT, "tests", "fixtures", "host.json")
FIXTURE_TRANSPORTS = os.path.join(FLEET_ROOT, "tests", "fixtures", "transports")

_spec = importlib.util.spec_from_file_location("render_time", SCRIPT)
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def eq(name, got, want):
    check(name, got == want, "got %r, want %r" % (got, want))


CITIES = [("Berlin", "Europe/Berlin"), ("Tokyo", "Asia/Tokyo"), ("Kolkata", "Asia/Kolkata")]
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
SUMMER = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def at(**delta):
    return NOW + timedelta(**delta)


# === 1. The pure function, with a fixed clock.
eq("past, under an hour",
   rt.render(at(minutes=-3, seconds=-30), NOW, CITIES),
   "4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)")
eq("past, over an hour: hours and minutes",
   rt.render(at(minutes=-75), NOW, CITIES),
   "1 hour 15 minutes ago (11:45 am Berlin, 7:45 pm Tokyo, 4:15 pm Kolkata)")
eq("past, whole hours: plural and no minutes part",
   rt.render(at(hours=-2), NOW, CITIES),
   "2 hours ago (11:00 am Berlin, 7:00 pm Tokyo, 3:30 pm Kolkata)")
eq("past a day: still hours, no day unit",
   rt.render(at(hours=-26, minutes=-5), NOW, CITIES),
   "26 hours 5 minutes ago (10:55 am Berlin, 6:55 pm Tokyo, 3:25 pm Kolkata)")
eq("future, exact",
   rt.render(at(minutes=25), NOW, CITIES),
   "in 25 minutes (1:25 pm Berlin, 9:25 pm Tokyo, 5:55 pm Kolkata)")
eq("future, an estimate: `in about`",
   rt.render(at(hours=1), NOW, CITIES, estimate=True),
   "in about 1 hour (2:00 pm Berlin, 10:00 pm Tokyo, 6:30 pm Kolkata)")
eq("future estimate past an hour keeps hours and minutes",
   rt.render(at(hours=1, minutes=1), NOW, CITIES, estimate=True),
   "in about 1 hour 1 minute (2:01 pm Berlin, 10:01 pm Tokyo, 6:31 pm Kolkata)")
eq("the estimate flag never decorates a past time",
   rt.render(at(minutes=-3, seconds=-30), NOW, CITIES, estimate=True),
   "4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)")
eq("within the current minute, future",
   rt.render(at(seconds=40), NOW, CITIES),
   "in less than a minute (1:00 pm Berlin, 9:00 pm Tokyo, 5:30 pm Kolkata)")
eq("within the current minute, the instant itself reads as past",
   rt.render(NOW, NOW, CITIES),
   "less than a minute ago (1:00 pm Berlin, 9:00 pm Tokyo, 5:30 pm Kolkata)")
# The delta counts whole minutes between the CLOCK minutes shown, not elapsed
# seconds: one second before 12:00 is shown as 11:59, so it reads "1 minute ago",
# and 20 seconds that cross a minute boundary read "in 1 minute". A renderer
# that floors elapsed seconds prints "in less than a minute" beside two clocks a
# minute apart.
eq("one second across a minute boundary agrees with the clock (past)",
   rt.render(at(seconds=-1), NOW, CITIES),
   "1 minute ago (12:59 pm Berlin, 8:59 pm Tokyo, 5:29 pm Kolkata)")
eq("twenty seconds across a minute boundary agree with the clock (future)",
   rt.render(at(minutes=1, seconds=10), NOW + timedelta(seconds=50), CITIES),
   "in 1 minute (1:01 pm Berlin, 9:01 pm Tokyo, 5:31 pm Kolkata)")
eq("midnight is 12, am; no leading zero",
   rt.render(at(hours=-12, minutes=-55), NOW, CITIES),
   "12 hours 55 minutes ago (12:05 am Berlin, 8:05 am Tokyo, 4:35 am Kolkata)")
eq("noon is 12, pm",
   rt.render(at(hours=-1), NOW, CITIES),
   "1 hour ago (12:00 pm Berlin, 8:00 pm Tokyo, 4:30 pm Kolkata)")

# Daylight saving: the same wall-clock UTC instant in July moves Berlin by one
# hour and leaves both zones without daylight saving where they were.
summer = rt.render(SUMMER - timedelta(minutes=3, seconds=30), SUMMER, CITIES)
eq("July: Berlin is on summer time, Tokyo and Kolkata unchanged",
   summer, "4 minutes ago (1:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)")

eq("the city order is the order given", rt.render(NOW, NOW, CITIES[::-1]),
   "less than a minute ago (5:30 pm Kolkata, 9:00 pm Tokyo, 1:00 pm Berlin)")

# Parsing: the forms a ledger, a chat timestamp and a scheduler fire carry.
eq("ISO with Z", rt.parse("2026-01-15T12:00Z"), NOW)
eq("ISO with an offset", rt.parse("2026-01-15T17:30+05:30"), NOW)
eq("epoch seconds", rt.parse("1768478400"), NOW)
eq("epoch seconds with a fraction (a chat message timestamp)",
   rt.parse("1768478400.000200").replace(microsecond=0), NOW)
for bad in ("2026-01-15T12:00", "yesterday", ""):
    try:
        rt.parse(bad)
        check("refuses %r" % bad, False, "parsed without error")
    except ValueError:
        check("refuses %r" % bad, True)


# === 2. The command line, against a temporary install built from the fixture.
def run(env_root, *args):
    env = dict(os.environ)
    env["FLEET_CONTEXT_ROOT"] = env_root
    if "FLEET_HOST_CONFIG" not in env and os.path.isfile(FIXTURE_HOST):
        env["FLEET_HOST_CONFIG"] = FIXTURE_HOST
    # manifest.load checks the enabled transports against the registry; the
    # fixture registry carries the working descriptor the fixture manifest
    # enables, so this test does not depend on which transport skills the
    # tree holds (fleetlib's test-only FLEET_TRANSPORTS_DIR).
    if os.path.isdir(FIXTURE_TRANSPORTS):
        env["FLEET_TRANSPORTS_DIR"] = FIXTURE_TRANSPORTS
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                       text=True, env=env)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def install_with(tmp, name, cities):
    """A copy of the fixture manifest whose reader cities are `cities`."""
    with open(os.path.join(FIXTURE_INSTALL, ".claude", "fleet.json"), encoding="utf-8") as f:
        m = json.load(f)
    m.setdefault("house_rules", {})["times"] = {
        "cities": [{"name": c, "tz": z} for c, z in cities]}
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".claude", "fleet.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
    return root


FIXED = ("--now", "2026-01-15T12:00:00Z")
if not os.path.isfile(os.path.join(FIXTURE_INSTALL, ".claude", "fleet.json")):
    check("NO VERDICT for the command-line layer: the fixture manifest "
          "tests/fixtures/install/.claude/fleet.json is missing, so nothing "
          "proves where the cities come from", False)
else:
    tmp = tempfile.mkdtemp(prefix="render-time-test-")
    try:
        three = install_with(tmp, "three", CITIES)
        rc, out, err = run(three, "--at", "2026-01-15T11:56:30Z", *FIXED)
        eq("CLI reads the install's cities", (rc, out),
           (0, "4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)"))
        if rc != 0:
            print("       stderr: " + err)
        two = install_with(tmp, "two", [CITIES[2], CITIES[0]])
        rc, out, _ = run(two, "--at", "2026-01-15T11:56:30Z", *FIXED)
        eq("a different install gives a different line: the cities are not built in",
           (rc, out), (0, "4 minutes ago (5:26 pm Kolkata, 12:56 pm Berlin)"))
        rc, out, _ = run(three, "--at", "2026-01-15T13:00Z", "--estimate", *FIXED)
        eq("CLI --estimate", (rc, out),
           (0, "in about 1 hour (2:00 pm Berlin, 10:00 pm Tokyo, 6:30 pm Kolkata)"))
        rc, out, _ = run(three, "--at", "1768478190", *FIXED)
        eq("CLI epoch seconds", (rc, out),
           (0, "4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)"))
        rc, out, _ = run(three, *FIXED)
        eq("CLI with no --at renders the instant itself", (rc, out),
           (0, "less than a minute ago (1:00 pm Berlin, 9:00 pm Tokyo, 5:30 pm Kolkata)"))
        rc, out, err = run(three, "--at", "2026-01-15T11:56", *FIXED)
        check("CLI refuses a time with no zone: exit 2, no line",
              rc == 2 and out == "" and "no zone" in err, "rc=%d out=%r err=%r" % (rc, out, err))
        rc, out, _ = run(three, "--at", "yesterday", *FIXED)
        check("CLI refuses an unparseable time: exit 2, no line", rc == 2 and out == "",
              "rc=%d out=%r" % (rc, out))
        empty = os.path.join(tmp, "no-install")
        os.makedirs(empty)
        rc, out, err = run(empty, "--at", "2026-01-15T11:56:30Z", *FIXED)
        check("CLI with no install context exits 3 and prints no line "
              "(no built-in fallback city)", rc == 3 and out == "",
              "rc=%d out=%r err=%r" % (rc, out, err))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print()
if _failures:
    print("FAILED: %d check(s): %s" % (len(_failures), "; ".join(_failures)))
    sys.exit(1)
print("ALL CHECKS PASSED")
