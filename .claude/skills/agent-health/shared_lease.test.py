#!/usr/bin/env python3
"""Offline guard for SHARED leases: agents sharing an account only when the pool
has fewer accounts than agents, the share named in the lease, read once per
sweep, and handed over as a group. Synthetic accounts, a temp directory, no
network, no agent.

    python3 shared_lease.test.py

pool_pick.py's header owns the rule (SHARED LEASES). What this file pins:

  1. SHARING IS REFUSED WHILE ACCOUNTS >= AGENTS. Two accounts, two agents: a
     `--take --share` of the other agent's account is refused and changes
     nothing, and the pick names the free account instead of a share.
  2. ONE ACCOUNT, TWO AGENTS: the pick offers the share (`"share": true`), the
     take with --share makes ONE lease naming BOTH, `--shares` prints "2 agents
     share account x", and `--release` collapses it back to one holder.
  3. THE SWEEP READS EACH ACCOUNT ONCE: driven by `--shares --json --roster`, a
     sweep over both holders appends one reading per window, under the section
     `shared:<account>`, and nothing under either agent; the next sweep, read by
     the OTHER holder because the first is down, still finds its baseline; and
     of two holders' snapshots the freshest is the one read.
  4. A HANDOVER MOVES THE WHOLE GROUP: the pick for one holder carries a
     `group_plan` for every holder; executed holder by holder with `--take`, it
     empties the old account - spreading the group over free accounts while they
     last, and with none free moving everyone onto the account another agent
     holds.

EXIT CODES: 0 PASS, 1 FAIL, 3 NO VERDICT (a control misbehaved: not a pass).

WHY EACH CONTROL IS LOAD-BEARING - read before deleting one
  * Each property has a mutation control: a deliberately BROKEN COPY of
    pool_pick.py on the same inputs must turn the check red - the head-count
    refusal removed (the share is taken), a lease that keeps one holder (the
    share names one), every holder marked as a reader (two readings per sweep),
    a group plan for the asking agent alone (the old account keeps a holder).
    A copy that still passes means the check cannot see what it is named for:
    NO VERDICT, never a pass.
  * Positive evidence the sweep reached its subject: each reading must have
    appended its rows, so "one reading" is never "no reading at all".
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
PICK = os.path.join(HERE, "pool_pick.py")
PARSE = os.path.join(HERE, "parse_usage.py")
sys.path.insert(0, HERE)
import parse_usage as pu  # noqa: E402

T0 = 1792152000  # 2026-10-16T12:00Z
passed, failed, broken = 0, [], []


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


tmp = tempfile.mkdtemp(prefix="shared-lease-test-")


def run(script, cfg, *args):
    p = subprocess.run([sys.executable, script, "--config", cfg, "--now", str(T0)] + list(args),
                       capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, None


def world(name, accounts, leases):
    """A config, a pool of `accounts`, a lease file and an empty usage ledger."""
    d = os.path.join(tmp, name)
    os.makedirs(d)
    pool = [{"username": a, "password": "fixture-not-real"} for a in accounts]
    for f, v in (("pool.json", pool), ("leases.json", leases)):
        with open(os.path.join(d, f), "w") as fh:
            json.dump(v, fh)
    with open(os.path.join(d, "agents.md"), "w") as fh:
        fh.write(pu.LEDGER_PREAMBLE)
    cfg = os.path.join(d, "config.json")
    with open(cfg, "w") as fh:
        json.dump({"accounts": {"pool_file": "pool.json", "lease_file": "leases.json",
                                "ledger_file": "agents.md", "handover_ledger_file": "handover.md"}}, fh)
    return cfg, os.path.join(d, "leases.json"), os.path.join(d, "agents.md")


def lease_file(path):
    return json.load(open(path))


def mutant(name, old, new):
    d = os.path.join(tmp, "mutant-" + name)
    os.mkdir(d)
    shutil.copy(PARSE, d)
    src = open(PICK).read()
    control("mutation '%s' applies exactly once" % name, src.count(old), 1)
    out = os.path.join(d, "pool_pick.py")
    with open(out, "w") as fh:
        fh.write(src.replace(old, new))
    return out


def snapshot(cfg_dir, five, written_at):
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, pu.SNAPSHOT_NAME), "w") as fh:
        json.dump({"written_at": written_at, "rate_limits": {
            "five_hour": {"used_percentage": five, "resets_at": T0 + 4 * 3600},
            "seven_day": {"used_percentage": 10, "resets_at": T0 + 5 * 86400}}}, fh)


try:
    # ------------------------------------------- 1. refused while accounts >= agents
    def refusal(script):
        cfg, lf, _ = world("refuse-" + os.path.basename(os.path.dirname(script)),
                           ["x@example.com", "y@example.com"],
                           {"x@example.com": {"agent": "ada", "since": "2026-10-16T00:00Z"}})
        before = open(lf).read()
        rc, out = run(script, cfg, "--take", "x@example.com", "--agent", "bob", "--share")
        return rc, (out or {}).get("reason", ""), open(lf).read() == before, cfg

    rc, reason, same, cfg = refusal(PICK)
    ok("2 accounts, 2 agents: --share of ada's account is REFUSED (exit 1), nothing changed",
       (rc, "sharing is REFUSED" in reason, same), (1, True, True))
    rc, out = run(PICK, cfg, "--agent", "bob")
    ok("...and the pick names the free account, not a share",
       ((out or {}).get("pick"), (out or {}).get("share")), ("y@example.com", False))
    m = mutant("no-head-count", "            if n_accounts >= n_agents:\n",
               "            if False:\n")
    control("with the head-count refusal removed the share is taken - the check sees the rule",
            refusal(m)[0], 0)

    # ------------------------------------------- 2. one account, two agents
    def one_account(script):
        cfg, lf, _ = world("one-" + os.path.basename(os.path.dirname(script)), ["x@example.com"],
                           {"x@example.com": {"agent": "ada", "since": "2026-10-16T00:00Z"}})
        rc_pick, p = run(script, cfg, "--agent", "bob")
        rc, out = run(script, cfg, "--take", "x@example.com", "--agent", "bob", "--share")
        return cfg, lf, (rc_pick, p), (rc, out)

    cfg, lf, (rcp, p), (rc, out) = one_account(PICK)
    ok("1 account, 2 agents: the pick offers x as a SHARE",
       (rcp, (p or {}).get("pick"), (p or {}).get("share")), (0, "x@example.com", True))
    ok("...--take --share exits 0 and names who it shares with",
       (rc, (out or {}).get("shared_with")), (0, ["ada"]))
    ok("...ONE lease on x naming BOTH holders", lease_file(lf).get("x@example.com", {}).get("agents"), ["ada", "bob"])
    before = open(lf).read()
    rc, out = run(PICK, cfg, "--take", "x@example.com", "--agent", "ada")
    ok("a holder re-taking its own shared account (no --share) is unchanged, not refused",
       (rc, (out or {}).get("unchanged"), open(lf).read() == before), (0, True, True))
    rc, view = run(PICK, cfg, "--shares", "--json")
    ok("--shares --json: one share, allowed, with its line",
       [(s["account"], s["agents"], s["allowed"], s["line"]) for s in (view or {}).get("shares", [])],
       [("x@example.com", ["ada", "bob"], True, "2 agents share account x@example.com (ada, bob)")])
    p = subprocess.run([sys.executable, PICK, "--config", cfg, "--shares"], capture_output=True, text=True)
    ok("--shares (text) prints the line", p.stdout.strip(), "2 agents share account x@example.com (ada, bob)")
    rc, out = run(PICK, cfg, "--release", "--agent", "bob", "--why", "bob leaves the fleet")
    ok("--release takes bob out; the share collapses to ada's own lease",
       (rc, lease_file(lf)), (0, {"x@example.com": {"agent": "ada", "since": "2026-10-16T00:00Z"}}))
    m = mutant("one-holder",
               '    return {"agent": hs[0], "since": since} if len(hs) == 1 else {"agents": hs, "since": since}',
               '    return {"agent": hs[-1], "since": since}')
    control("a lease that keeps one holder fails the 'names BOTH' check",
            lease_file(one_account(m)[1]).get("x@example.com", {}).get("agents"), None)

    # ------------------------------------------- 3. the sweep reads each account once
    def sweep(script, cfg, ledger, roster, t, snaps):
        """What the agent-health sweep does with the shares view: read each agent
        unless another holder covers it, under the section the view names, with
        every holder's snapshot so the freshest is read."""
        rc, view = run(script, cfg, "--shares", "--json", "--roster", ",".join(roster))
        appended = []
        for agent in roster:
            info = (view or {}).get("by_agent", {}).get(agent)
            if info and not info["read"]:
                continue
            group = next((s["agents"] for s in view["shares"] if s["account"] == info["account"]),
                         [agent]) if info else [agent]
            dirs = sum([["--rate-limits", snaps[h]] for h in group], [])
            p = subprocess.run([sys.executable, PARSE] + dirs + [
                "--agent", info["section"] if info else agent, "--account", info["account"],
                "--ledger", ledger, "--append", "--now", str(t)], capture_output=True, text=True)
            appended.append((agent, json.loads(p.stdout)["ledger"]["rows_appended"]))
        return appended

    def sweep_world(script):
        cfg, lf, ledger = world("sweep-" + os.path.basename(os.path.dirname(script)), ["x@example.com"],
                                {"x@example.com": {"agents": ["ada", "bob"], "since": "2026-10-16T00:00Z"}})
        snaps = {"ada": os.path.join(tmp, "cfg-ada"), "bob": os.path.join(tmp, "cfg-bob")}
        snapshot(snaps["ada"], 40, T0 - 600)
        snapshot(snaps["bob"], 55, T0 - 60)
        first = sweep(script, cfg, ledger, ["ada", "bob"], T0, snaps)
        return cfg, ledger, snaps, first

    cfg, ledger, snaps, first = sweep_world(PICK)
    control("the sweep reached its subject: the reading appended its two windows", first[:1], [("ada", 2)])
    ok("one sweep over both holders: ONE reading (ada reads, bob is covered)", first, [("ada", 2)])
    rows = pu.read_ledger_rows(ledger, "shared:x@example.com")
    ok("...attributed to the account: section shared:x@example.com, account x",
       sorted((r["window_name"], r["account"]) for r in rows),
       [("Current session", "x@example.com"), ("Current week (all models)", "x@example.com")])
    ok("...and nothing under either agent",
       (pu.read_ledger_rows(ledger, "ada"), pu.read_ledger_rows(ledger, "bob")), ([], []))
    ok("...of the two holders' snapshots the FRESHEST (bob's, 55%) was read",
       [r["percent"] for r in rows if r["window_name"] == "Current session"], ["55"])
    snapshot(snaps["bob"], 70, T0 + 1700)
    second = sweep(PICK, cfg, ledger, ["bob"], T0 + 1800, snaps)
    rows = [r for r in pu.read_ledger_rows(ledger, "shared:x@example.com")
            if r["window_name"] == "Current session"]
    ok("with ada down, bob reads the account and finds its baseline (not a first reading)",
       (second, rows[-1]["velocity"], rows[-1]["decision"] != "first-reading"), ([("bob", 2)], "30.0", True))
    m = mutant("everyone-reads", '            by_agent[h] = {"account": u, "section": section, "read": h == reader,',
               '            by_agent[h] = {"account": u, "section": section, "read": True,')
    control("a view that marks every holder a reader gives TWO readings per sweep",
            len(sweep_world(m)[3]), 2)

    # ------------------------------------------- 4. a handover moves the whole group
    def group_move(script, accounts, leases, asker):
        cfg, lf, _ = world("group-%s-%d" % (os.path.basename(os.path.dirname(script)), len(accounts)),
                           accounts, leases)
        rc, p = run(script, cfg, "--agent", asker, "--current", "x@example.com")
        plan = (p or {}).get("group_plan") or {}
        for h in sorted(plan):
            args = ["--take", plan[h]["to"], "--agent", h] + (["--share"] if plan[h]["share"] else [])
            run(script, cfg, *args)
        return rc, plan, lease_file(lf)

    since = "2026-10-16T00:00Z"
    rc, plan, after = group_move(
        PICK, ["x@example.com", "y@example.com"],
        {"x@example.com": {"agents": ["ada", "bob"], "since": since},
         "y@example.com": {"agent": "carl", "since": since}}, "ada")
    ok("no free account: the plan moves BOTH holders onto carl's account, shared",
       (rc, {h: (v["to"], v["share"]) for h, v in plan.items()}),
       (0, {"ada": ("y@example.com", True), "bob": ("y@example.com", True)}))
    ok("...executed, x is empty and y names all three", (sorted(after), after.get("y@example.com", {}).get("agents")),
       (["y@example.com"], ["ada", "bob", "carl"]))
    rc, plan, after = group_move(
        PICK, ["x@example.com", "y@example.com", "z@example.com", "w@example.com"],
        {"x@example.com": {"agents": ["ada", "bob", "carl"], "since": since},
         "y@example.com": {"agents": ["dan", "erin"], "since": since}}, "bob")
    ok("two free accounts for three holders: one alone, two sharing the last",
       {h: (v["to"], v["share"]) for h, v in plan.items()},
       {"ada": ("z@example.com", False), "bob": ("w@example.com", True), "carl": ("w@example.com", True)})
    ok("...executed, x is empty and every holder has moved",
       ("x@example.com" in after, after.get("z@example.com"), after.get("w@example.com", {}).get("agents")),
       (False, {"agent": "ada", "since": "2026-10-16T12:00Z"}, ["bob", "carl"]))
    m = mutant("asker-only", "            plan = {h: targets[min(i, len(targets) - 1)] for i, h in enumerate(group)}",
               "            plan = {h: targets[min(i, len(targets) - 1)] for i, h in enumerate([agent])}")
    control("a plan for the asking agent alone leaves a holder on the old account",
            "x@example.com" in group_move(m, ["x@example.com", "y@example.com"],
                                          {"x@example.com": {"agents": ["ada", "bob"], "since": since},
                                           "y@example.com": {"agent": "carl", "since": since}}, "ada")[2],
            True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("")
if broken:
    print("NO VERDICT - %d control(s) misbehaved: %s" % (len(broken), "; ".join(broken)))
    print("Do NOT read this as a pass. Fix the control, then re-run.")
    sys.exit(3)
print("passed %d, failed %d" % (passed, len(failed)))
sys.exit(0 if not failed else 1)
