#!/usr/bin/env python3
"""pool-mode.test.py - agent-revive/installation/check FAILS when the account pool
file, which holds every pool account's password, is readable or writable by
anyone but its owner.

    python3 .claude/skills/agent-revive/installation/pool-mode.test.py

The pool picker refuses a token file that is readable by others (pool_pick.py,
"readable by others"); the pool file holds passwords, the more valuable of the
two, and check is what an operator runs to ask whether the install is sound. So
a pool file with any group or other permission bit is a leg that FAILS (exit 1,
named in the verdict line), never one that only prints its mode. A mode
narrower than 600 (400) passes: what matters is that nobody else may read it.

THE HARNESS is check.test.py's: the real check copied into a throwaway fleet
tree, every leg made to pass by a fake (its docstring). It is imported, not
copied, so the two files cannot drift apart. The pool file's CONTENTS are never
read by the check, and this test never writes anything secret into it.

THE CONTROL: with the pool file at 600 the check exits 0 with OK. Without that,
an exit 1 below could be any leg failing. Each failing case then also asserts
the verdict line names accounts.pool_file, so the 1 is about this leg. If the
control does not hold, the run is NO VERDICT (exit 3), never a pass.

macOS: the same cases run with the Darwin host of the harness (BSD stat -f is
the only mode reader there), so the mode is read the way a Mac reads it.

Exit codes: 0 pass; 1 a case failed; 3 NO VERDICT.
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location("agent_revive_check_test", os.path.join(HERE, "check.test.py"))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        failures.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="agent-revive-pool-mode-test-")
    try:
        w = harness.build(tmp)
        for host, h in (("linux", w), ("macos", w["darwin"])):
            os.chmod(w["pool"], 0o600)
            rc, last, out = harness.run(h)
            if rc != 0 or not last.startswith("OK:"):
                print(out)
                print(f"NO VERDICT: {host}: the control (pool file mode 600, every other leg passing) did not "
                      f"exit 0 with OK (exit {rc}, last line {last!r})")
                return 3
            print(f"[PASS] {host} control: pool file mode 600, exit 0 with OK")
            for mode in (0o644, 0o640, 0o604, 0o660):
                os.chmod(w["pool"], mode)
                rc, last, out = harness.run(h)
                check(f"{host}: pool file mode {mode:o}: exit 1, the verdict names accounts.pool_file, and the "
                      f"leg says the mode is not 600",
                      rc == 1 and "accounts.pool_file" in last and f"mode {mode:o}" in out and "NOT 600" in out,
                      f"rc={rc} last={last!r}")
            os.chmod(w["pool"], 0o400)
            rc, last, out = harness.run(h)
            check(f"{host}: pool file mode 400 (narrower than 600): exit 0 with OK",
                  rc == 0 and last.startswith("OK:"), f"rc={rc} last={last!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), "; ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
