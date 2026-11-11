#!/usr/bin/env python3
"""The watcher of a PLACEHOLDER transport: it honours the watcher CLI and refuses.

    <transport skill>/watch.py [--once]

Every placeholder transport's `watch.py` is a symlink to this file, so the
refusal has one implementation. The transport is read from the `transport.json`
beside the path this script was INVOKED through (`abspath`, never `realpath`:
the realpath is this directory, which holds no descriptor), so the line names
the transport whose watcher was started.

Exit codes are the watcher contract's (SKILL.md, "Watcher contract"):

    2  always - a placeholder refuses, and a usage error is a 2 as well

stdout stays empty: a line there would be read by a follower as a delivered
message. The refusal is one stderr line,

    WATCH-GUARD <transport> transport is a placeholder: not implemented

which every transport's default follower filter passes, so an operator who
starts one by hand reads why nothing arrives. Exit 2, not 0, because 0 is the
watcher contract's guard refusal (another copy holds the lock, or the config's
owner is a different agent) - a state that clears by itself - while a
placeholder never starts doing anything.
"""
import json
import os
import sys


def main(argv: list) -> int:
    if any(a != "--once" for a in argv):
        print(f"usage: watch.py [--once] (got {' '.join(argv)})", file=sys.stderr)
        return 2
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "transport.json"), encoding="utf-8") as f:
            name = json.load(f)["name"]
    except (OSError, ValueError, KeyError) as e:
        print(f"usage: run a placeholder transport's watch.py, not this file "
              f"(no transport.json beside {here}: {type(e).__name__})", file=sys.stderr)
        return 2
    print(f"WATCH-GUARD {name} transport is a placeholder: not implemented", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
