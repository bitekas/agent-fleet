#!/usr/bin/env python3
"""Render a time for a person: its distance from now, then the clock in each reader city.

    render_time.py [--at TIME] [--now TIME] [--estimate]

prints one line in the `agent` skill's section 4 format:

    <delta> (<h:mm am|pm> <city>, <h:mm am|pm> <city>, ...)

    4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)
    in about 1 hour (2:00 pm Berlin, 10:00 pm Tokyo, 6:30 pm Kolkata)

--at        the time to render: ISO 8601 with a zone (`2026-10-09T00:29Z`,
            `...+05:30`) or epoch seconds (a chat message timestamp, the `at`
            of a scheduler fire). Default: the current instant.
--now       the instant the delta is measured from. Default: the clock. It
            exists so a rendering is reproducible - a test, or "as of" a
            recorded moment - and never needs to be typed otherwise.
--estimate  marks a future time as an estimate: `in about N minutes`.

THE CITIES ARE THE INSTALL'S, READ THROUGH fleetlib, AND NEVER DEFAULTED HERE.
They are `house_rules.times.cities` in the install manifest, with the fleet
default applied by `manifest.settings()` when the key is absent. If no install
resolves, this script exits 3 and prints no line: a silent fallback to some
built-in city would hand every reader a clock in a zone they do not live in,
and the line would look exactly as authoritative as a correct one.

WHY THE CLOCK AND THE ZONE DATABASE, IN THE SAME COMMAND THAT WRITES THE LINE.
An offset typed by hand is right until the next daylight-saving change and
silently wrong after it; a remembered time drifts across a long session. Both
halves of the line come from here.

A TIME WITH NO ZONE IS REFUSED (exit 2). A naive time would be read as this
machine's zone, which is a guess: a source that prints none is converted only
once its zone is established.

THE DELTA COUNTS WHOLE MINUTES BETWEEN THE TWO CLOCK MINUTES SHOWN, so it always
agrees with the clock times printed beside it. It has no day unit: past a day
it still spells hours (`26 hours 5 minutes ago`).

Exit: 0 printed, 2 usage or an unparseable time, 3 no install context or a
zone that does not load.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse(s):
    """An aware datetime from epoch seconds or ISO 8601 with a zone.

    Raises ValueError for anything else, a naive ISO time included.
    """
    try:
        return datetime.fromtimestamp(float(s), timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("no zone in %r (needs Z or an offset)" % s)
    return t


def span(n):
    """`N hours M minutes` for a positive whole number of minutes."""
    h, m = divmod(n, 60)
    parts = (["%d hour%s" % (h, "" if h == 1 else "s")] if h else []) + \
            (["%d minute%s" % (m, "" if m == 1 else "s")] if m else [])
    return " ".join(parts)


def clock(t, zone):
    """`h:mm am|pm` in `zone`: no leading zero, lower case, no abbreviation."""
    c = t.astimezone(ZoneInfo(zone))
    return "%d:%02d %s" % (c.hour % 12 or 12, c.minute, "am" if c.hour < 12 else "pm")


def render(t, now, cities, estimate=False):
    """The line for time `t` seen from `now`; `cities` is [(name, zone), ...]."""
    def minute(d):
        return d.replace(second=0, microsecond=0)
    n = int((minute(t) - minute(now)).total_seconds() // 60)
    if n == 0:
        delta = "in less than a minute" if t > now else "less than a minute ago"
    elif n > 0:
        delta = "in " + ("about " if estimate else "") + span(n)
    else:
        delta = span(-n) + " ago"
    return "%s (%s)" % (delta, ", ".join("%s %s" % (clock(t, z), c) for c, z in cities))


def install_cities():
    """[(name, zone), ...] from the install manifest, through fleetlib.

    The fleet root is found from realpath(__file__), never abspath: invoked
    through an agent's personal skill link, abspath is the link path under the
    agent's config directory, and three parents up from there is not the fleet.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.realpath(__file__)))))
    sys.path.insert(0, os.path.join(root, "lib"))
    from fleetlib import manifest, paths  # noqa: E402 - path set just above
    settings = manifest.settings(manifest.load(paths.install_root()))
    return [(c["name"], c["tz"]) for c in settings["house_rules"]["times"]["cities"]]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="render_time.py",
        description="Render a time as its delta from now plus the clock in each "
                    "reader city of the install.")
    ap.add_argument("--at", help="time to render: ISO 8601 with a zone, or epoch seconds")
    ap.add_argument("--now", help="instant the delta is measured from (default: the clock)")
    ap.add_argument("--estimate", action="store_true",
                    help="mark a future time as an estimate (`in about ...`)")
    a = ap.parse_args(argv)
    try:
        now = parse(a.now) if a.now else datetime.now(timezone.utc)
        t = parse(a.at) if a.at else now
    except ValueError as e:
        print("render_time.py: %s" % e, file=sys.stderr)
        return 2
    try:
        cities = install_cities()
    except Exception as e:  # noqa: BLE001 - every fleetlib refusal is the same verdict
        print("render_time.py: no install context, so no reader cities: %s: %s"
              % (type(e).__name__, e), file=sys.stderr)
        return 3
    if not cities:
        print("render_time.py: the install names no reader city "
              "(house_rules.times.cities is empty)", file=sys.stderr)
        return 3
    try:
        print(render(t, now, cities, a.estimate))
    except (ZoneInfoNotFoundError, ValueError) as e:
        print("render_time.py: a reader city's zone does not load: %s" % e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
