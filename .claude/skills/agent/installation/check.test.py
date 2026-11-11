#!/usr/bin/env python3
"""Regression guard for agent/installation/check.

Runs the real check as a subprocess against the fleet's FIXTURE INSTALL
(tests/fixtures/install) and throwaway agent homes in a temp directory, so the
exit-code contract is exercised end to end. Nothing outside the temp directory
is written, and no real agent home is read: CLAUDE_CONFIG_DIR, HOME and the
host settings file all point into the temp tree.

WHAT THIS PINS, and what removing each case would let through:

  - The check reads CONTEXT.md FROM THE INSTALL CONTEXT through fleetlib. The
    green case alone cannot show that - a check reading any CONTEXT.md with a
    matching row would pass it - so a copy of the fixture install whose home
    row has a different shape must turn the same home into NO VERDICT, naming
    that install's file. If the "different shape" case ever passes, the check
    is not reading the install's CONTEXT.md and its green means nothing.
  - realpath, never abspath: the check run through a symlinked skill directory
    (an agent's personal skill link) must still find fleetlib. With abspath it
    looks for `lib/` beside the agent's config directory and says NO VERDICT.
  - No install context, an unparseable row and an unresolvable `<agents-root>`
    are NO VERDICT (exit 1), never a green: the subject was not reached.
  - The optional HOME_DIR argument is the negative control and needs no
    install at all: a bare home must exit 2.
  - A blockers file this process can read and not write is STALE (exit 1), not
    OK: the hourly timer's operation is a write. The writable home is the
    control, and the check must leave its bytes and mtime as they were.

Run: python3 .claude/skills/agent/installation/check.test.py
Exits 1 on any failure, 3 when a case's state could not be built (as root a 0444
file is writable), 0 otherwise.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "templates", "blockers.md")
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
FIXTURE_CONTEXT = os.path.join(FIXTURE_INSTALL, ".claude", "skills", "agent", "CONTEXT.md")

_failures = []
_no_verdict = []  # a case whose state could not be built: exit 3, never a pass
_tmp = tempfile.mkdtemp(prefix="agent-check-test-")


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


AGENTS = os.path.join(_tmp, "agents")
HOME = os.path.join(AGENTS, "ada")
HOST = os.path.join(_tmp, "host.json")
write(HOST, json.dumps({"schema": 1, "agents_root": AGENTS,
                        "fleet_checkout": os.path.join(AGENTS, "fleet"),
                        "claims_dir": os.path.join(AGENTS, "claims")}))
os.makedirs(os.path.join(HOME, ".claude"))
with open(TEMPLATE, encoding="utf-8") as f:
    write(os.path.join(HOME, "blockers", "blockers.md"), f.read())


def run(*args, install=FIXTURE_INSTALL, home=HOME, host=HOST, script=CHECK):
    env = dict(os.environ)
    env.update(FLEET_CONTEXT_ROOT=install, FLEET_HOST_CONFIG=host,
               CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"), HOME=home)
    p = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def install_copy(name, context_text):
    """A copy of the fixture install whose agent CONTEXT.md is `context_text`."""
    root = os.path.join(_tmp, name)
    shutil.copytree(FIXTURE_INSTALL, root)
    write(os.path.join(root, ".claude", "skills", "agent", "CONTEXT.md"), context_text)
    return root


if not os.path.isfile(os.path.join(FIXTURE_INSTALL, ".claude", "fleet.json")) \
        or not os.path.isfile(FIXTURE_CONTEXT):
    check("NO VERDICT: the fixture install (tests/fixtures/install/.claude/fleet.json and "
          ".claude/skills/agent/CONTEXT.md) is incomplete, so nothing here can run", False)
else:
    with open(FIXTURE_CONTEXT, encoding="utf-8") as f:
        fixture_context = f.read()

    # === 0. POSITIVE CONTROL: the fixture install, a home with the template's file.
    rc, out = run()
    check("fixture install + installed home exits 0", rc == 0 and out.startswith("OK"),
          "rc=%d out=%r" % (rc, out))
    check("the OK line names the blockers file it read",
          os.path.join(HOME, "blockers", "blockers.md") in out, "out=%r" % out)

    # === 1. DISCRIMINATING CONTROL: the install's CONTEXT.md is the one read.
    other = install_copy("other-shape", fixture_context.replace(
        "`<agents-root>/<agent>`", "`/tmp/agent-check-elsewhere/<agent>`", 1))
    rc, out = run(install=other)
    check("an install whose home row has another shape gives NO VERDICT for the same home",
          rc == 1 and "does not match" in out and "/tmp/agent-check-elsewhere/<agent>" in out,
          "rc=%d out=%r" % (rc, out))

    # === 2. realpath: run through a symlinked skill directory.
    links = os.path.join(_tmp, "agent-config", "skills")
    os.makedirs(links)
    os.symlink(SKILL, os.path.join(links, "agent"))
    rc, out = run(script=os.path.join(links, "agent", "installation", "check"))
    check("through a personal skill link, fleetlib is still found (realpath, not abspath)",
          rc == 0 and out.startswith("OK"), "rc=%d out=%r" % (rc, out))

    # === 3. Unreached subject: NO VERDICT, exit 1, never a green.
    empty = os.path.join(_tmp, "no-install")
    os.makedirs(empty)
    rc, out = run(install=empty)
    check("no install context is NO VERDICT", rc == 1 and "NO VERDICT" in out
          and "no install context" in out, "rc=%d out=%r" % (rc, out))
    relabeled = install_copy("relabeled", fixture_context.replace(
        "| home directory |", "| agent home |", 1))
    rc, out = run(install=relabeled)
    check("a relabeled home row is NO VERDICT naming the install's file",
          rc == 1 and "has no `home directory` row" in out
          and (relabeled in out or os.path.realpath(relabeled) in out),
          "rc=%d out=%r" % (rc, out))
    rc, out = run(host=os.path.join(_tmp, "no-such-host.json"))
    check("<agents-root> with no host settings is NO VERDICT",
          rc == 1 and "NO VERDICT" in out and "<agents-root>" in out, "rc=%d out=%r" % (rc, out))

    # === 4. The three states of the subject itself.
    bare = os.path.join(AGENTS, "grace")
    os.makedirs(os.path.join(bare, ".claude"))
    rc, out = run(home=bare)
    check("a home with no blockers file exits 2", rc == 2 and "NOT INSTALLED" in out,
          "rc=%d out=%r" % (rc, out))
    stale = os.path.join(AGENTS, "alan")
    write(os.path.join(stale, "blockers", "blockers.md"),
          "| Expected | From | Why | Requested | Last pinged |\n|---|---|---|---|---|\n")
    os.makedirs(os.path.join(stale, ".claude"))
    rc, out = run(home=stale)
    check("a file with the five-column header (no Where) exits 1 STALE",
          rc == 1 and "STALE" in out and "Where" in out, "rc=%d out=%r" % (rc, out))

    # === 5. NEGATIVE CONTROL: the argument path, which needs no install at all.
    rc, out = run(bare, install=empty)
    check("check <bare home> exits 2 with no install context", rc == 2 and "NOT INSTALLED" in out,
          "rc=%d out=%r" % (rc, out))
    rc, out = run(os.path.join(_tmp, "no-such-home"), install=empty)
    check("check <missing home> is NO VERDICT", rc == 1 and "NO VERDICT" in out,
          "rc=%d out=%r" % (rc, out))

    # === 6. WRITABILITY: the timer WRITES `Last pinged` into the file, so a file
    # this process can read and not write is not installed for it. The green home
    # of case 0 is the control: same template content, writable, exits 0. Its file
    # must also be untouched by the check (opened for append, nothing written).
    green = os.path.join(HOME, "blockers", "blockers.md")

    def state(path):
        with open(path, "rb") as f:
            return os.stat(path).st_mtime_ns, f.read()

    before = state(green)
    rc, out = run()
    # rc 0 is what proves the run reached the writability leg, the last one.
    check("the writability leg writes nothing (exit 0, bytes and mtime unchanged)",
          rc == 0 and state(green) == before, "rc=%d out=%r" % (rc, out))
    readonly = os.path.join(_tmp, "readonly-home")
    ro_file = os.path.join(readonly, "blockers", "blockers.md")
    with open(TEMPLATE, encoding="utf-8") as f:
        write(ro_file, f.read())
    os.chmod(ro_file, 0o444)
    try:
        os.close(os.open(ro_file, os.O_WRONLY | os.O_APPEND))
        builds = False
    except PermissionError:
        builds = True
    if not builds:
        # As root a 0444 file is writable, so the state under test cannot be built
        # here: that is NO VERDICT on the leg (exit 3), never a pass.
        print("[NO VERDICT] this process can write a 0444 file (root?), so the "
              "not-writable state cannot be built")
        _no_verdict.append("read-only blockers file")
    else:
        rc, out = run(readonly, install=empty)
        check("a read-only blockers file exits 1 STALE naming the write and the chmod fix",
              rc == 1 and "STALE" in out and "cannot be written" in out and ro_file in out
              and "chmod u+w" in out, "rc=%d out=%r" % (rc, out))
    os.chmod(ro_file, 0o644)

shutil.rmtree(_tmp, ignore_errors=True)

print()
if _failures:
    print("FAILED: %d check(s): %s" % (len(_failures), "; ".join(_failures)))
    sys.exit(1)
if _no_verdict:
    print("NO VERDICT on: %s" % "; ".join(_no_verdict))
    sys.exit(3)
print("ALL CHECKS PASSED")
