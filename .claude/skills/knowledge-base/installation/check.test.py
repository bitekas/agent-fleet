#!/usr/bin/env python3
"""Regression guard for knowledge-base/installation/check.

Runs the real check as a subprocess against the fleet's FIXTURE INSTALL
(tests/fixtures/install) and against copies of it in a temp directory, so the
exit-code contract is exercised end to end. Nothing outside the temp directory
is written, and no real store is read.

WHAT THIS PINS, and what removing each case would let through:

  - config.json and .install-state.json are read FROM THE INSTALL CONTEXT
    through fleetlib. Against the fixture install as committed, the check must
    name the fixture's own store (proving it read that config.json and
    resolved its RELATIVE store.root against the config file's directory) and
    report STALE because the fixture records only `fixture-host` (proving it
    read that state file). A copy of the install with this machine recorded
    must then go green while naming the COPY's store - the same check, a
    different install, a different answer.
  - One entry per host: another machine's record beside this one's leaves
    this one current; another machine's record ALONE is stale here. The
    single-host form an older INSTRUCTION.md wrote is read as one entry.
  - realpath, never abspath: run through a symlinked skill directory, the
    check still finds fleetlib and its own check_indexes.py.
  - No install context is NO VERDICT (exit 1): the subject was not reached.
  - A store whose indexes are broken is STALE, not OK, whatever the record.

If this machine's hostname is literally `fixture-host`, the first case cannot
discriminate, and the run says NO VERDICT and fails rather than pass on a
control that measured nothing.

Run: python3 .claude/skills/knowledge-base/installation/check.test.py
Exits nonzero on any failure.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
SKILL = os.path.dirname(HERE)
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
KB = os.path.join(".claude", "skills", "knowledge-base")
ME = socket.gethostname()

_failures = []
_tmp = tempfile.mkdtemp(prefix="kb-check-test-")


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def run(install, script=CHECK, **env_extra):
    env = dict(os.environ)
    env["FLEET_CONTEXT_ROOT"] = install
    env.update(env_extra)
    p = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def names(path, text):
    return path in text or os.path.realpath(path) in text


def copy(name, state=None, config=None):
    """A copy of the fixture install, with its state file and config replaced
    when given (None keeps the fixture's; False deletes the file)."""
    root = os.path.join(_tmp, name)
    shutil.copytree(FIXTURE_INSTALL, root)
    for rel, value in (("installation/.install-state.json", state), ("config.json", config)):
        path = os.path.join(root, KB, rel)
        if value is False:
            os.remove(path)
        elif value is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(value if isinstance(value, str) else json.dumps(value))
    return root


def entry(version=1):
    return {"version": version, "installed_at": "2026-01-15T12:00:00Z", "by": "INSTRUCTION.md"}


if not os.path.isfile(os.path.join(FIXTURE_INSTALL, ".claude", "fleet.json")) \
        or not os.path.isfile(os.path.join(FIXTURE_INSTALL, KB, "config.json")):
    check("NO VERDICT: the fixture install (tests/fixtures/install/.claude/fleet.json and "
          + KB + "/config.json) is incomplete, so nothing here can run", False)
elif ME == "fixture-host":
    check("NO VERDICT: this machine is named fixture-host, so the fixture's own record "
          "cannot be told from this machine's", False)
else:
    fixture_store = os.path.join(FIXTURE_INSTALL, KB, "fixture-store")

    # === 1. The fixture install as committed: its config and its state file are read.
    rc, out = run(FIXTURE_INSTALL)
    check("fixture install: STALE, because only fixture-host is recorded",
          rc == 1 and "no install is recorded for this machine" in out and "fixture-host" in out,
          "rc=%d out=%r" % (rc, out))
    check("fixture install: the relative store.root resolved against config.json's directory",
          names(fixture_store, out), "out=%r" % out)

    # === 2. POSITIVE CONTROL: the same install with this machine recorded.
    both = copy("both", state={"hosts": {"fixture-host": entry(), ME: entry()}})
    rc, out = run(both)
    check("this machine recorded beside another: exit 0", rc == 0 and out.startswith("OK"),
          "rc=%d out=%r" % (rc, out))
    check("...naming the COPY's store, not the fixture's",
          names(os.path.join(both, KB, "fixture-store"), out) and not names(fixture_store, out),
          "out=%r" % out)

    # === 3. The single-host form.
    rc, out = run(copy("legacy-mine", state=dict(entry(), host=ME)))
    check("single-host form for this machine: exit 0", rc == 0 and out.startswith("OK"),
          "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("legacy-other", state=dict(entry(), host="other-host")))
    check("single-host form for another machine: STALE here",
          rc == 1 and "no install is recorded for this machine" in out and "other-host" in out,
          "rc=%d out=%r" % (rc, out))

    # === 4. Versions.
    rc, out = run(copy("older", state={"hosts": {ME: entry(0)}}))
    check("an older recorded version is STALE", rc == 1 and "installed version 0" in out,
          "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("newer", state={"hosts": {ME: entry(99)}}))
    check("a newer recorded version is STALE", rc == 1 and "NEWER" in out,
          "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("garbled", state="{not json"))
    check("an unreadable state file is STALE", rc == 1 and "unreadable" in out,
          "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("unrecorded", state=False))
    check("no state file is STALE", rc == 1 and "no install is recorded" in out,
          "rc=%d out=%r" % (rc, out))

    # === 5. Not installed.
    no_cfg = copy("no-config", config=False)
    rc, out = run(no_cfg)
    check("no config.json in the install context: exit 2 naming that path",
          rc == 2 and "NOT INSTALLED" in out and names(os.path.join(no_cfg, KB, "config.json"), out),
          "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("no-store", state={"hosts": {"other-host": entry()}},
                       config={"store": {"root": "missing-store"}}))
    check("a missing store: exit 2, and the line says where it is recorded instead",
          rc == 2 and "no store at" in out and "other-host" in out, "rc=%d out=%r" % (rc, out))

    # === 6. Expansion: an environment variable in store.root.
    rc, out = run(copy("expanded", state={"hosts": {ME: entry()}},
                       config={"store": {"root": "${KB_CHECK_TEST_STORE}"}}),
                  KB_CHECK_TEST_STORE=fixture_store)
    check("store.root is expanded (${VAR})", rc == 0 and names(fixture_store, out),
          "rc=%d out=%r" % (rc, out))

    # === 7. A broken store is STALE whatever the record says.
    broken = copy("broken-store", state={"hosts": {ME: entry()}})
    with open(os.path.join(broken, KB, "fixture-store", "orphan.md"), "w", encoding="utf-8") as f:
        f.write("# Orphan\n")
    rc, out = run(broken)
    check("an unlinked file in the store is STALE via check_indexes.py",
          rc == 1 and "fails check_indexes.py" in out and "orphan.md" in out,
          "rc=%d out=%r" % (rc, out))

    # === 8. realpath: through a symlinked skill directory.
    links = os.path.join(_tmp, "agent-config", "skills")
    os.makedirs(links)
    os.symlink(SKILL, os.path.join(links, "knowledge-base"))
    rc, out = run(both, script=os.path.join(links, "knowledge-base", "installation", "check"))
    check("through a personal skill link: still exit 0 (realpath, not abspath)",
          rc == 0 and out.startswith("OK"), "rc=%d out=%r" % (rc, out))

    # === 9. No install context.
    empty = os.path.join(_tmp, "no-install")
    os.makedirs(empty)
    rc, out = run(empty)
    check("no install context is NO VERDICT, exit 1", rc == 1 and "NO VERDICT" in out,
          "rc=%d out=%r" % (rc, out))

shutil.rmtree(_tmp, ignore_errors=True)

print()
if _failures:
    print("FAILED: %d check(s): %s" % (len(_failures), "; ".join(_failures)))
    sys.exit(1)
print("ALL CHECKS PASSED")
