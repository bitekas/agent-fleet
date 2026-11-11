#!/usr/bin/env python3
"""Offline guard for pool_pick.py. No network, no tmux, no agent, no real file.

    python3 pool_pick.test.py

Every case runs the REAL command line (`python3 pool_pick.py ...`) against the
fixtures in fixtures/pool/ with the clock pinned at 2026-10-16T12:00Z, so the
argument parsing, the exit codes and the JSON are what is measured, not a
function called around them. The lease-writing cases copy the lease fixture into
a private temp dir first; nothing under fixtures/ is ever written.

EXIT CODES: THREE, NEVER TWO
  0  PASS        every property holds
  1  FAIL        at least one property is broken - each one is named
  3  NO VERDICT  a CONTROL misbehaved, so the instrument is not established and
                 this file refuses to pronounce. ⚠️ 3 IS NOT A SMALLER PASS: a
                 consumer must treat any non-zero as "not green".

WHY EACH CONTROL IS LOAD-BEARING - read before deleting one
  * PRE-GATE. Every fixture is asserted present and non-empty, and the first
    pick is asserted to have READ the ledger (an account carries a reading time)
    before any pick is compared. Without it a renamed fixture reads as "no
    history", every account predicts 0%, and the suite reports on its plumbing.
  * THE NEGATIVE CONTROL: a MISSING ledger and a MISSING lease file must each be
    exit 2 with a null pick - never a pick. Both are the instrument not reaching
    its subject, and the comfortable reading of each ("every account idle",
    "nothing leased") hands an agent an account that is at 95% or that another
    agent is running on. If either ever comes back exit 0 with a pick, the
    picker can no longer tell "read and chosen" from "read nothing", and no
    pick it issues means anything.
  * MUTATION CONTROLS. Each rule the pick depends on - leases excluded, a passed
    reset predicting 0%, the soonest reset preferred, the latest reading
    standing - is DISABLED in a copy of the real script, and the copy must pick
    differently on the same fixture. A rule the fixture cannot see go missing is
    a rule this suite does not test; each control proves the fixture CAN see it,
    and that the mutation really applied. A control that did not apply, or a
    mutant that still agrees with the real script, is NO VERDICT.
  * THE INSTALL CONTEXT. With no --config and no $AGENT_REVIVE_CONFIG the config is
    agent-revive's in the install context (fleetlib; the fixture install in the
    fleet's CI). Its exclude list names a reason no other config here carries, so
    seeing that reason on the account proves the file was READ; an install
    context that does not resolve is exit 2 with a null pick, never a pick.
  * NO PASSWORD REACHES ANY OUTPUT. Every run's stdout and stderr is collected and
    searched for every fixture password, INCLUDING a truncated pool file whose
    only password is a sentinel - the one path that could echo file bytes is the
    JSON error, and well-formed fixtures exercise everything but that. A control
    proves the strings really are in the fixtures, so the absence is not vacuous.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
# The fixture install context, unless the runner already named one (tests/run-all.sh does).
os.environ.setdefault("FLEET_CONTEXT_ROOT", os.path.join(FLEET_ROOT, "tests", "fixtures", "install"))
os.environ.pop("AGENT_REVIVE_CONFIG", None)
SCRIPT = os.path.join(HERE, "pool_pick.py")
FX = os.path.join(HERE, "fixtures", "pool")
CFG = os.path.join(FX, "config.fixture.json")
NOW = "1792152000"  # 2026-10-16T12:00Z

passed, failed, broken = 0, [], []
outputs = []  # every stdout+stderr this file produced, for the password scan


def ok(what, got, want):
    global passed
    if got == want:
        print("ok   - %s" % what)
        passed += 1
    else:
        print("FAIL - %s: expected %r, got %r" % (what, want, got))
        failed.append(what)


def control(what, got, want):
    global passed
    if got == want:
        print("ok   - control: %s" % what)
        passed += 1
    else:
        print("CONTROL BROKEN - %s: expected %r, got %r" % (what, want, got))
        broken.append(what)


def run(*args, script=SCRIPT, config=CFG):
    cmd = [sys.executable, script, "--config", config, "--now", NOW] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True)
    outputs.append(p.stdout + p.stderr)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = None
    return p.returncode, out, p.stderr


def status(out, user):
    for a in (out or {}).get("accounts", []):
        if a["username"] == user:
            return a
    return {}


tmp = tempfile.mkdtemp(prefix="pool-pick-test-")
try:
    # ---------------------------------------------------------------- pre-gate
    for f in ("config.fixture.json", "pool.json", "leases.json", "ledger.md"):
        p = os.path.join(FX, f)
        control("fixture %s exists and is non-empty" % f,
                os.path.isfile(p) and os.path.getsize(p) > 0, True)

    rc, out, _ = run("--agent", "alpha", "--current", "g@example.com")
    control("the first pick READ the ledger (d carries its reading time)",
            status(out, "d@example.com").get("reading_at"), "2026-10-16T10:00Z")

    # ---------------------------------------------------------------- the pick
    ok("a clean pick exits 0", rc, 0)
    ok("the pick is j: soonest reset (Oct 18 09:00, shared with d), idle longer than d",
       out and out["pick"], "j@example.com")
    ok("the reason names the tie and how it was broken",
       "broken by idle-longest" in (out or {}).get("reason", ""), True)
    ok("no reconciliation problem when alpha is on g and holds g's lease",
       out and out["problems"], [])
    ok("g is the current account", status(out, "g@example.com").get("status"), "current")
    ok("f is leased, and says to whom",
       (status(out, "f@example.com").get("status"), status(out, "f@example.com").get("leased_by")),
       ("leased", "beta"))
    ok("a is excluded by the config's list, with its reason",
       status(out, "a@example.com").get("note"), "excluded: Google rejects its sign-in")
    ok("b: two weekly windows (85%, 0%) - the HIGHER one is the prediction",
       (status(out, "b@example.com").get("status"), status(out, "b@example.com").get("predicted_weekly_pct")),
       ("over-limit", 85))
    ok("c: a recorded reset that has PASSED predicts 0%",
       status(out, "c@example.com").get("predicted_weekly_pct"), 0)
    ok("c: ...and the reset rolls forward 7 days (Oct 12 13:00 -> Oct 19 13:00)",
       status(out, "c@example.com").get("next_reset"), "2026-10-19T13:00Z")
    ok("d: the LATEST reading stands (20%), not the older 90%",
       status(out, "d@example.com").get("predicted_weekly_pct"), 20)
    ok("e: no ledger row - predicted 0%, reset unknown",
       (status(out, "e@example.com").get("predicted_weekly_pct"), status(out, "e@example.com").get("next_reset")),
       (0, None))
    ok("h: 75% is under the exclusion line but short of the headroom line",
       status(out, "h@example.com").get("status"), "low-headroom")
    ok("usage follows the ACCOUNT: c and f are read out of another agent's section",
       (status(out, "c@example.com").get("reading_at"), status(out, "f@example.com").get("reading_at")),
       ("2026-10-10T10:00Z", "2026-10-16T09:00Z"))

    _, out2, _ = run("--exclude", "j@example.com")
    ok("without j, d is next (same reset)", out2 and out2["pick"], "d@example.com")
    _, out3, _ = run("--exclude", "j@example.com", "--exclude", "d@example.com")
    ok("without j and d, c (predicted 0%, Oct 19) beats e (reset unknown sorts LAST)",
       out3 and out3["pick"], "c@example.com")
    _, out4, _ = run(*sum([["--exclude", u + "@example.com"] for u in ("j", "d", "c")], []))
    ok("with only e left among the healthy, the never-read account is picked",
       out4 and out4["pick"], "e@example.com")
    _, out5, _ = run(*sum([["--exclude", u + "@example.com"] for u in ("j", "d", "c", "e")], []))
    ok("no account with >= 30% headroom -> the least-used of the rest (h, 75%)",
       out5 and out5["pick"], "h@example.com")
    ok("...and the reason SAYS no account had the headroom",
       "NO account has >= 30% headroom" in (out5 or {}).get("reason", ""), True)
    rc6, out6, _ = run(*sum([["--exclude", u + "@example.com"] for u in ("j", "d", "c", "e", "h")], []))
    ok("pool exhausted -> exit 1", rc6, 1)
    ok("pool exhausted -> pick is null, and the reason says exhausted",
       (out6 and out6["pick"], "pool exhausted" in (out6 or {}).get("reason", "")), (None, True))
    ok("without --current, the pick is still computed (case 3b runs it this way)",
       run()[1]["pick"], "j@example.com")

    # ------------------------------------------------------- reconciliation
    rc, out, _ = run("--agent", "beta", "--current", "g@example.com")
    ok("current account leased to ANOTHER agent -> exit 1, no pick",
       (rc, out and out["pick"]), (1, None))
    ok("...and the problem names both agents",
       any("leased to alpha, not beta" in p for p in (out or {}).get("problems", [])), True)
    rc, out, _ = run("--agent", "alpha", "--current", "zz@example.com")
    ok("current account in NO pool entry -> exit 1, no pick, case 4",
       (rc, out and out["pick"], any("case 4" in p for p in (out or {}).get("problems", []))),
       (1, None, True))
    rc, out, _ = run("--agent", "alpha", "--current", "e@example.com")
    probs = (out or {}).get("problems", [])
    ok("current account unleased while the agent holds another lease -> both named",
       (rc, any("carries no lease" in p for p in probs), any("also holds a lease on g@example.com" in p for p in probs)),
       (1, True, True))

    # ------------------------------------------------ the NEGATIVE CONTROL
    rc, out, err = run("--ledger", os.path.join(tmp, "no-such-ledger.md"))
    ok("NEGATIVE CONTROL: a missing ledger is exit 2 with a null pick, never 'all idle'",
       (rc, out and out.get("pick")), (2, None))
    rc, out, err = run("--leases", os.path.join(tmp, "no-such-leases.json"))
    ok("NEGATIVE CONTROL: a missing lease file is exit 2 with a null pick, never 'nothing leased'",
       (rc, out and out.get("pick")), (2, None))

    # --------------------------------------------------------- pool defects
    def pool_file(name, text):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p
    rc, out, err = run("--pool", os.path.join(tmp, "no-such-pool.json"))
    ok("no pool file -> exit 2, names case 8", (rc, "case 8" in err), (2, True))
    trunc = pool_file("trunc.json", '[{"username":"a@example.com","password":"truncated-pool-canary"},\n')
    rc, out, err = run("--pool", trunc)
    ok("a truncated pool file -> exit 2, names case 9", (rc, "case 9" in err), (2, True))
    stream = pool_file("stream.json", '{"username":"a@example.com","password":"p1"}\n'
                                      '{"username":"b@example.com","password":"p2"}\n')
    ok("a JSON stream (a list missing its [ ]) -> exit 2", run("--pool", stream)[0], 2)
    obj = pool_file("object.json", '{"username":"a@example.com","password":"p1"}\n')
    ok("a single object is not a pool -> exit 2", run("--pool", obj)[0], 2)
    dup = pool_file("dup.json", '[{"username":"a@example.com","password":"p1"},'
                                '{"username":"a@example.com","password":"p2"}]\n')
    rc, out, err = run("--pool", dup)
    ok("duplicate usernames -> exit 2, names case 10", (rc, "case 10" in err), (2, True))
    forged = pool_file("forged.json", '[{"username":"a@example.com\\tnext","password":"p1"}]\n')
    ok("a tab in a username -> exit 2 (a forged column is refused)", run("--pool", forged)[0], 2)
    # An entry the sign-in driver would refuse to type is MALFORMED (case 9), not a
    # quietly excluded row: listed as fine, it reads as fine until a sign-in fails.
    # The negative control is the same one-entry pool with a real password, which
    # must NOT fault - otherwise the three refusals below prove nothing about the
    # password check.
    good1 = pool_file("good1.json", '[{"username":"a@example.com","password":"fake-pw-1"}]\n')
    control("a one-entry pool WITH a password is read (exit is not 2)", run("--pool", good1)[0] != 2, True)
    for name, body in (("empty", '""'), ("blank", '"   \\t "'), ("null", "null")):
        bad = pool_file("pw-%s.json" % name,
                        '[{"username":"a@example.com","password":"fake-pw-1"},'
                        '{"username":"b@example.com","password":%s}]\n' % body)
        rc, out, err = run("--pool", bad)
        ok("a %s password -> exit 2, names case 9 and entry 1 (b@example.com)" % name,
           (rc, "case 9" in err, "pool entry 1 (b@example.com)" in err), (2, True, True))
        ok("...and the refusal carries no other entry's password", "fake-pw-1" in err, False)
    nopw = pool_file("pw-missing.json", '[{"username":"a@example.com"}]\n')
    ok("a missing password -> exit 2, names case 9", (lambda r: (r[0], "case 9" in r[2]))(run("--pool", nopw)), (2, True))

    # ------------------------------------------------------------ --take
    lease = os.path.join(tmp, "leases.json")
    shutil.copy(os.path.join(FX, "leases.json"), lease)
    os.chmod(lease, 0o644)
    rc, out, _ = run("--leases", lease, "--take", "e@example.com", "--agent", "alpha")
    with open(lease, encoding="utf-8") as fh:
        after = json.load(fh)
    ok("--take e for alpha -> exit 0", rc, 0)
    ok("...releases alpha's old lease on g and leases e, stamped now",
       (sorted(after), after.get("e@example.com")),
       (["e@example.com", "f@example.com"], {"agent": "alpha", "since": "2026-10-16T12:00Z"}))
    ok("...leaves another agent's lease alone", after.get("f@example.com", {}).get("agent"), "beta")
    ok("...and keeps the file's mode", stat.S_IMODE(os.stat(lease).st_mode), 0o644)
    before = open(lease, "rb").read()
    rc, out, _ = run("--leases", lease, "--take", "f@example.com", "--agent", "alpha")
    ok("--take of an account leased to ANOTHER agent -> exit 1, file untouched",
       (rc, open(lease, "rb").read() == before), (1, True))
    rc, out, _ = run("--leases", lease, "--take", "zz@example.com", "--agent", "alpha")
    ok("--take of an account in no pool entry -> exit 1, file untouched",
       (rc, open(lease, "rb").read() == before), (1, True))
    rc, out, _ = run("--leases", lease, "--take", "e@example.com", "--agent", "alpha")
    ok("re-taking the account already held keeps its since",
       (rc, out and out.get("unchanged"), json.load(open(lease))["e@example.com"]["since"]),
       (0, True, "2026-10-16T12:00Z"))
    ok("--take without --agent -> exit 2", run("--leases", lease, "--take", "e@example.com")[0], 2)

    # ------------------------------------------------------ mutation controls
    # Each rule is disabled in a COPY of the real script (parse_usage.py beside
    # it, which it imports). The copy must disagree with the real pick.
    def mutant(name, old, new):
        d = os.path.join(tmp, name)
        os.mkdir(d)
        shutil.copy(os.path.join(HERE, "parse_usage.py"), d)
        src = open(SCRIPT, encoding="utf-8").read()
        control("mutation '%s' applies exactly once" % name, src.count(old), 1)
        with open(os.path.join(d, "pool_pick.py"), "w", encoding="utf-8") as fh:
            fh.write(src.replace(old, new))
        return os.path.join(d, "pool_pick.py")

    m = mutant("no-leases", "        elif hs:\n", "        elif False:\n")
    control("with leases IGNORED the pick becomes f (leased, soonest reset) - the fixture can see the lease rule",
            run(script=m)[1]["pick"], "f@example.com")
    m = mutant("no-passed-reset", "if reset is not None and reset <= now:", "if False:")
    excl = sum([["--exclude", u + "@example.com"] for u in ("j", "d")], [])
    control("with the passed-reset rule gone, c keeps its stale 60% - the fixture can see that rule",
            status(run(*excl, script=m)[1], "c@example.com").get("predicted_weekly_pct"), 60)
    m = mutant("latest-first", "    at = max(r[\"epoch\"] for r in weekly)\n",
               "    at = min(r[\"epoch\"] for r in weekly)\n")
    control("reading the OLDEST weekly row instead makes d over-limit - the fixture can see the latest-reading rule",
            status(run(script=m)[1], "d@example.com").get("status"), "over-limit")
    m = mutant("no-reset-order", "        return (e[\"_reset\"] is None, e[\"_reset\"] or 0,\n",
               "        return (False, 0,\n")
    control("without the soonest-reset order the pick changes - the fixture can see that rule",
            run(script=m)[1]["pick"] != "j@example.com", True)
    m = mutant("idle-reversed", "e[\"_seen\"] if e[\"_seen\"] is not None else float(\"-inf\"))",
               "-(e[\"_seen\"] or 0))")
    control("with the idle-longest tie-break reversed, d wins the tie - the fixture can see that rule",
            run(script=m)[1]["pick"], "d@example.com")

    # ------------------------------------------------- the install context
    def run_ctx(*args, ctx=None):
        env = dict(os.environ)
        if ctx is not None:
            env["FLEET_CONTEXT_ROOT"] = ctx
        cmd = [sys.executable, SCRIPT, "--now", NOW,
               "--pool", os.path.join(FX, "pool.json"), "--leases", os.path.join(FX, "leases.json"),
               "--ledger", os.path.join(FX, "ledger.md")] + list(args)
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        outputs.append(p.stdout + p.stderr)
        try:
            return p.returncode, json.loads(p.stdout), p.stderr
        except ValueError:
            return p.returncode, None, p.stderr

    rc, out, err = run_ctx("--agent", "alpha", "--current", "g@example.com")
    ok("no --config: agent-revive's config in the install context is the one read (its exclude reason shows)",
       (rc, status(out, "c@example.com").get("note")), (0, "excluded: fixture install context"))
    empty = os.path.join(tmp, "no-install-here")
    os.mkdir(empty)
    rc, out, err = run_ctx("--agent", "alpha", "--current", "g@example.com", ctx=empty)
    ok("an install context that does not resolve -> exit 2, null pick, naming the remedy",
       (rc, (out or {}).get("pick", "absent"), "pass --config or set AGENT_REVIVE_CONFIG" in err),
       (2, None, True))

    # An install with no agent-revive config has no pool: --shares (what the
    # install's closing summary and `fleet status` run) prints nothing and exits
    # 0 there. The controls are the same install with every other mode, and with
    # the missing config NAMED, each still exit 2: so the 0 is "no config, no
    # pool" and not a --shares that stopped reading its config.
    bare = os.path.join(os.path.realpath(tmp), "install-without-agent-revive")  # install_root() realpaths it
    os.makedirs(os.path.join(bare, ".claude"))
    shutil.copy(os.path.join(os.environ["FLEET_CONTEXT_ROOT"], ".claude", "fleet.json"),
                os.path.join(bare, ".claude", "fleet.json"))
    missing = os.path.join(bare, ".claude", "skills", "agent-revive", "config.json")
    control("the bare install resolves and has no agent-revive config",
            (os.path.isfile(os.path.join(bare, ".claude", "fleet.json")), os.path.exists(missing)), (True, False))

    def bare_run(*args):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_REVIVE_CONFIG"}
        env["FLEET_CONTEXT_ROOT"] = bare
        p = subprocess.run([sys.executable, SCRIPT, "--now", NOW] + list(args), capture_output=True,
                           text=True, env=env, stdin=subprocess.DEVNULL)
        outputs.append(p.stdout + p.stderr)
        return p.returncode, p.stdout, p.stderr

    ok("no agent-revive config: --shares prints nothing and exits 0", bare_run("--shares"), (0, "", ""))
    rc, so, _ = bare_run("--shares", "--json")
    ok("no agent-revive config: --shares --json is the empty view, exit 0",
       (rc, json.loads(so) if rc == 0 else so),
       (0, {"pool": None, "accounts": 0, "agents": 0, "sharing_allowed": False, "shares": [], "by_agent": {}}))
    rc, _, err = bare_run("--agent", "alpha")
    control("no agent-revive config: the pick still refuses, exit 2 naming the file",
            (rc, "no config at %s" % missing in err), (2, True))
    rc, _, err = bare_run("--shares", "--config", missing)
    control("a missing config NAMED by --config: --shares still refuses, exit 2",
            (rc, "no config at %s" % missing in err), (2, True))

    # ------------------------------------------------- no password in any output
    with open(os.path.join(FX, "pool.json"), encoding="utf-8") as fh:
        pws = [e["password"] for e in json.load(fh) if e["password"]]
    pws.append("truncated-pool-canary")
    control("the fixture pool really carries the passwords this scan looks for",
            len(pws) >= 9 and all("fixture-pw-" in p or "canary" in p for p in pws), True)
    control("the scan has outputs to search (it is not passing on nothing)", len(outputs) >= 20, True)
    leaked = sorted({p for p in pws for o in outputs if p in o})
    ok("no password reaches stdout or stderr on any path, error paths included", leaked, [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("")
if broken:
    print("NO VERDICT - %d control(s) misbehaved, so the instrument is not established: %s"
          % (len(broken), "; ".join(broken)))
    print("Do NOT read this as a pass. Fix the control, then re-run.")
    sys.exit(3)
print("passed %d, failed %d" % (passed, len(failed)))
sys.exit(0 if not failed else 1)
