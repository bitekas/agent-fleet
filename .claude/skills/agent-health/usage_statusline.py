#!/usr/bin/env python3
"""A Claude Code status-line command that keeps the session's plan usage on disk.

    "statusLine": {"type": "command", "command": "<this file>"}

in a token agent's own settings (`$CLAUDE_CONFIG_DIR/settings.json`). Claude Code
runs the command with the status-line JSON on stdin after each change to the
conversation and at the soonest rate-limit reset, and draws what it prints.

WHY IT EXISTS. An agent on the `token` auth mode (`claude setup-token`) cannot be
swept off /usage: that dialog fetches its plan rows only for a sign-in carrying
the `user:profile` scope, which a setup-token token does not (parse_usage.py,
THE SECOND INPUT). The status-line input carries the same session's
`rate_limits.five_hour` and `rate_limits.seven_day` from its own inference
responses. This command writes them to `<config dir>/fleet-usage.json`, and
`parse_usage.py --rate-limits <config dir>` reads them with no keystroke into
the agent's pane.

WHAT IT KEEPS. The last reading of EACH window, merged: Claude Code drops a
window from the input once its reset has passed, and keeping the last reading
with its reset time is what lets the parser report that window at 0% rather
than as missing. The file is replaced atomically, so a sweep never reads half
of it.

IT NEVER FAILS THE STATUS LINE. Any error - no input, no config dir, a full
disk - prints nothing and exits 0: a status line that crashes is drawn as an
error on the agent's screen on every turn, which is a cost to the agent this
command exists to protect.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import parse_usage as pu  # noqa: E402 - the reader owns the file's name and windows


def snapshot_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, pu.SNAPSHOT_NAME)


def merge(old, new_rl):
    out = dict(old.get("rate_limits") or {}) if isinstance(old, dict) else {}
    for key, _name, _window, _period in pu.SNAPSHOT_WINDOWS:
        w = (new_rl or {}).get(key)
        if isinstance(w, dict) and "used_percentage" in w and "resets_at" in w:
            out[key] = {"used_percentage": w["used_percentage"], "resets_at": w["resets_at"]}
    return out


def main():
    data = json.loads(sys.stdin.read() or "{}")
    path = snapshot_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    merged = merge(old, data.get("rate_limits"))
    if merged and merged != (old.get("rate_limits") if isinstance(old, dict) else None):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".fleet-usage-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"written_at": int(time.time()), "rate_limits": merged}, fh)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = (data.get("rate_limits") or {}).get(key)
        if isinstance(w, dict) and "used_percentage" in w:
            parts.append("%s %d%%" % (label, round(float(w["used_percentage"]))))
    print(" | ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - see IT NEVER FAILS THE STATUS LINE
        pass
    sys.exit(0)
