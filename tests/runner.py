#!/usr/bin/env python3
"""runner.py - the two jobs tests/run-all.sh cannot do in portable bash.

run-all.sh runs under /bin/bash 3.2 (macOS) as well as bash 5, and macOS ships
no GNU `timeout`; bash 3.2 has no associative arrays to look a test up in a
parsed list. Stdlib only.

Usage:
  python3 tests/runner.py timeout <seconds> -- <command> [<arg>...]
      Run <command> as the leader of a new process group and exit with its
      status (128+N when signal N ended it). When <seconds> pass first, send
      SIGTERM to the whole group, SIGKILL after a 10-second grace, and exit 124:
      GNU timeout's contract, plus the kill escalation. A SIGTERM, SIGINT or
      SIGHUP this helper receives is passed on to the group. Exit 127 when the
      command does not exist, 126 when it cannot be executed.

  python3 tests/runner.py platforms <platforms.json> <os> <test>...
      Check the platform list against the discovered <test>s and print one
      line, <path> TAB <only> TAB <reason>, for each test that does not run on
      <os> (linux or macos), in the list's order. The file is
      {"tests": [{"path": ..., "only": "linux"|"macos", "reason": ...}, ...]};
      keys starting with "_" are comments. Exit 1, every finding on stderr as
      "platforms: <finding>", when the file cannot be read or parsed, or an
      entry names no discovered test, repeats a path, has an "only" that is
      neither linux nor macos, has an empty reason, or carries an unknown key.
"""

import json
import os
import signal
import subprocess
import sys
import threading

GRACE = 10
OSES = ("linux", "macos")
ENTRY_KEYS = {"path", "only", "reason"}


def run_timeout(secs, argv):
    try:
        proc = subprocess.Popen(argv, process_group=0)
    except FileNotFoundError as exc:
        print(f"runner.py: cannot run {argv[0]}: {exc}", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"runner.py: cannot execute {argv[0]}: {exc}", file=sys.stderr)
        return 126

    def signal_group(sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    def forward(signum, _frame):
        signal_group(signum)

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, forward)

    timed_out = threading.Event()

    def expire():
        timed_out.set()
        print(f"runner.py: {argv[0]} timed out after {secs:g}s; SIGTERM to process group {proc.pid}",
              file=sys.stderr, flush=True)
        signal_group(signal.SIGTERM)
        try:
            proc.wait(GRACE)
        except subprocess.TimeoutExpired:
            print(f"runner.py: still running after {GRACE}s; SIGKILL to process group {proc.pid}",
                  file=sys.stderr, flush=True)
            signal_group(signal.SIGKILL)

    timer = threading.Timer(secs, expire)
    timer.daemon = True
    timer.start()
    rc = proc.wait()
    timer.cancel()
    if timed_out.is_set():
        # the leader is gone, but a member may still be in its grace period
        signal_group(signal.SIGKILL)
        return 124
    return 128 - rc if rc < 0 else rc


def platform_skips(path, os_name, tests):
    findings = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return [f"{path}: cannot read: {type(exc).__name__}: {exc}"], []
    entries = data.get("tests") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [f"{path}: no \"tests\" list at the top level"], []
    discovered = set(tests)
    seen, skips = set(), []
    for n, e in enumerate(entries):
        where = f"{path}: tests[{n}]"
        if not isinstance(e, dict):
            findings.append(f"{where}: not an object")
            continue
        bad = []
        test, only, reason = e.get("path"), e.get("only"), e.get("reason")
        if isinstance(test, str):
            where += f" ({test})"
        extra = sorted(k for k in e if k not in ENTRY_KEYS and not k.startswith("_"))
        if extra:
            bad.append(f"unknown key(s) {', '.join(extra)}")
        if not isinstance(test, str) or test not in discovered:
            bad.append("names no discovered test (stale or misspelled path)")
        elif test in seen:
            bad.append("listed twice")
        if only not in OSES:
            bad.append(f"\"only\" must be one of {', '.join(OSES)}")
        if not isinstance(reason, str) or not reason.strip():
            bad.append("has no reason")
        elif "\t" in reason or "\n" in reason:
            bad.append("reason must be one line with no tab")
        if isinstance(test, str):
            seen.add(test)
        findings += [f"{where}: {b}" for b in bad]
        if not bad and only != os_name:
            skips.append((test, only, reason.strip()))
    return findings, skips


def main(argv):
    if len(argv) >= 4 and argv[0] == "timeout" and argv[2] == "--":
        try:
            secs = float(argv[1])
        except ValueError:
            secs = -1
        if secs > 0:
            return run_timeout(secs, argv[3:])
    elif len(argv) >= 3 and argv[0] == "platforms":
        findings, skips = platform_skips(argv[1], argv[2], argv[3:])
        for f in findings:
            print(f"platforms: {f}", file=sys.stderr)
        if findings:
            return 1
        for test, only, reason in skips:
            print(f"{test}\t{only}\t{reason}")
        return 0
    print("usage: runner.py timeout <seconds> -- <command> [<arg>...]\n"
          "       runner.py platforms <platforms.json> <os> <test>...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
