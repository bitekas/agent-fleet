#!/usr/bin/env python3
"""Offline guard for the account pool AS A MECHANISM: register, sweep, pick,
lease, ledger. Synthetic accounts, a temp directory, no network, no tmux, no agent.

    python3 pool_mechanism.test.py

pool_pick.test.py owns WHICH account the pick is and why, clause by clause, on a
fixed fixture. This file owns the pieces that only mean something together:

  1. REGISTER - the one way an account enters the pool. Two synthetic accounts
     are registered through `pool_pick.py --register` from stdin; the pool, the
     lease file and the usage ledger are created, every credential file is 0600,
     a token is written in the header shape an agent's auth file carries, and a
     line that is not a setup-token token is refused.
  2. THE HANDOVER, END TO END - an agent on the first account fills its short
     window fast; three sweeps through `parse_usage.py --rate-limits` (the token
     agent's input) record first-reading, watch, switch-projection; the picker
     then names the OTHER account, the same one twice; `--take
     --install-token` moves the lease, installs that account's token 0600 and
     writes the handover-ledger row.
  3. LEASES NEVER DOUBLE-ASSIGN - RACERS real interpreters behind a file gate all
     `--take` one account for different agents: exactly one wins, every loser
     names the winner, the lease file names the winner, one ledger row.
  4. THE LEDGER ROUND-TRIPS - what --append wrote reads back through the
     ledger's own reader as the same values, and a reset written in the screen's
     shape resolves back to the snapshot's own instant.
  5. THE STATUS-LINE WRITER - usage_statusline.py keeps the last reading of each
     window, never fails the status line, and a passed reset reads 0%.

EXIT CODES: 0 PASS, 1 FAIL (each failure named), 3 NO VERDICT - a control
misbehaved, so the instrument is not established and nothing is pronounced. 3
is NOT a smaller pass.

WHY EACH CONTROL IS LOAD-BEARING - read before deleting one
  * Every mutation control runs a deliberately BROKEN COPY of the real script
    on the same inputs and requires the check to go RED on it: the two-check
    projection rule removed (the third sweep must stop being a switch), the
    current account no longer excluded (the pick must become the account the
    agent is already on), the installed token's mode loosened to 0644, the
    lease lock removed with a widening sleep (the race must find more than one
    winner), a reset written without its minutes (the round trip must break).
    A check the broken copy also passes cannot see the defect it is named for.
    A control whose mutation did not apply, or whose broken copy still passes,
    is NO VERDICT, never a pass.
  * THE NAIVE RACE IS WHY A ONE-WINNER RACE MEANS ANYTHING. A harness whose
    racers never overlap reports one winner for ANY take, locked or not. The
    lock-free copy must produce more than one winner on the same harness; if it
    does not, the race result is NO VERDICT.
  * POSITIVE EVIDENCE THE SUBJECT WAS REACHED: every racer must report; the
    scenario's sweeps must each have APPENDED rows (a sweep that read nothing
    appends nothing); the pick must have read the ledger (the first account
    carries a reading time).
  * NO CREDENTIAL REACHES ANY OUTPUT: every stdout and stderr this file
    produced is searched for each synthetic token and password, and a control
    proves the search strings are the ones registered.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import importlib.util

HERE = os.path.dirname(os.path.realpath(__file__))
PICK = os.path.join(HERE, "pool_pick.py")
PARSE = os.path.join(HERE, "parse_usage.py")
STATUS = os.path.join(HERE, "usage_statusline.py")
sys.path.insert(0, HERE)
import parse_usage as pu  # noqa: E402

ADA, GRACE = "ada@example.com", "grace@example.com"
TOKENS = {ADA: "sk-ant-oat01-" + "A" * 80, GRACE: "sk-ant-oat01-" + "G" * 80}
PASSWORD = "fixture-password-not-real-7"
T0 = 1792152000  # 2026-10-16T12:00Z
RACERS = 8

passed, failed, broken, outputs = 0, [], [], []


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


def run(argv, stdin=None, env=None):
    p = subprocess.run([sys.executable] + argv, input=stdin, capture_output=True,
                       text=True, env=env)
    outputs.append(p.stdout + p.stderr)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = None
    return p.returncode, out, p.stderr


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def mutant(tmp, name, script, old, new, extra=(), more=()):
    """A copy of `script` with `old` replaced by `new` (and each (old, new) pair in
    `more`), beside copies of `extra`."""
    d = os.path.join(tmp, "mutant-" + name)
    os.mkdir(d)
    for f in extra:
        shutil.copy(os.path.join(HERE, f), d)
    src = open(script, encoding="utf-8").read()
    for o, n in ((old, new),) + tuple(more):
        control("mutation '%s' applies exactly once" % name, src.count(o), 1)
        src = src.replace(o, n)
    out = os.path.join(d, os.path.basename(script))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(src)
    return out


def snapshot(cfg_dir, five, seven, five_reset, seven_reset):
    with open(os.path.join(cfg_dir, pu.SNAPSHOT_NAME), "w", encoding="utf-8") as fh:
        json.dump({"written_at": 0, "rate_limits": {
            "five_hour": {"used_percentage": five, "resets_at": five_reset},
            "seven_day": {"used_percentage": seven, "resets_at": seven_reset}}}, fh)


tmp = tempfile.mkdtemp(prefix="pool-mechanism-test-")
try:
    secrets = os.path.join(tmp, "secrets")
    state = os.path.join(tmp, "state")
    os.mkdir(state)
    cfg = os.path.join(tmp, "config.json")
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump({"accounts": {
            "pool_file": os.path.join(secrets, "pool.json"),
            "lease_file": os.path.join(state, "leases.json"),
            "ledger_file": os.path.join(state, "agents.md"),
            "handover_ledger_file": os.path.join(state, "handover.md")}}, fh)
    P = [PICK, "--config", cfg]
    pool = os.path.join(secrets, "pool.json")
    leases = os.path.join(state, "leases.json")
    ledger = os.path.join(state, "agents.md")
    handover = os.path.join(state, "handover.md")

    # ------------------------------------------------------------ 1. register
    rc, out, err = run(P + ["--register", ADA, "--token-stdin", "--home-agent", "alpha"],
                       stdin=TOKENS[ADA] + "\n")
    ok("register ada's token -> exit 0", rc, 0)
    ok("...creates the pool, the lease file and the usage ledger",
       sorted(os.path.basename(p) for p in (out or {}).get("created", [])
              if not os.path.isdir(p)), ["agents.md", "leases.json", "pool.json"])
    rc, out, _ = run(P + ["--register", GRACE, "--token-stdin"], stdin=TOKENS[GRACE] + "\n")
    ok("register grace's token -> exit 0, the pool now holds 2", (rc, (out or {}).get("accounts")), (0, 2))
    rc, out, _ = run(P + ["--register", GRACE, "--password-stdin"], stdin=PASSWORD + "\n")
    ok("a second register for grace adds a password and keeps the token",
       (rc, sorted(k for k in json.load(open(pool))[1] if k != "home_agent")),
       (0, ["password", "token_file", "username"]))
    entries = {e["username"]: e for e in json.load(open(pool))}
    ok("the pool file is 0600", mode(pool), 0o600)
    ok("every token file is 0600, in a 0700 directory",
       (sorted(mode(e["token_file"]) for e in entries.values()),
        mode(os.path.dirname(entries[ADA]["token_file"]))), ([0o600, 0o600], 0o700))
    ok("a token file carries the auth header the agent's auth file is read by",
       pu_header := json.loads(subprocess.run(
           [sys.executable, PICK, "--read-auth-file", entries[ADA]["token_file"]],
           capture_output=True, text=True).stdout),
       {"file": entries[ADA]["token_file"], "auth": "token", "account": ADA})
    ok("the lease file starts empty", json.load(open(leases)), {})
    before = open(pool, "rb").read()
    rc, out, err = run(P + ["--register", "alan@example.com", "--token-stdin"],
                       stdin="sk-ant-api03-" + "K" * 80 + "\n")
    ok("an API key pasted as a token is refused (exit 2) and the pool is untouched",
       (rc, open(pool, "rb").read() == before), (2, True))
    rc, out, err = run(P + ["--register", "alan@example.com"], stdin=TOKENS[ADA])
    ok("register with no credential flag is refused (exit 2)", rc, 2)
    bad_cfg = os.path.join(tmp, "bad-config.json")
    with open(bad_cfg, "w", encoding="utf-8") as fh:
        json.dump({"accounts": {"pool_file": os.path.join(tmp, "fresh", "pool.json"),
                                "lease_file": os.path.join(tmp, "fresh", "leases.json"),
                                "ledger_file": os.path.join(tmp, "no-such-dir", "agents.md")}}, fh)
    rc, out, err = run([PICK, "--config", bad_cfg, "--register", ADA, "--token-stdin"],
                       stdin=TOKENS[ADA] + "\n")
    ok("a register that cannot create the ledger refuses BEFORE writing anything",
       (rc, os.path.exists(os.path.join(tmp, "fresh"))), (2, False))

    # --------------------------------------------- 2. the handover, end to end
    rc, out, _ = run(P + ["--take", ADA, "--agent", "alpha", "--why", "first sign-in",
                          "--now", str(T0 - 3600)])
    ok("alpha takes ada (its first lease)", (rc, (out or {}).get("taken")), (0, ADA))
    alpha_cfg = os.path.join(tmp, "alpha-claude")
    os.mkdir(alpha_cfg)
    five_reset, seven_reset = T0 + 4 * 3600, T0 + 5 * 86400

    def sweep(t, five, script=PARSE, led=ledger):
        snapshot(alpha_cfg, five, 10, five_reset, seven_reset)
        return run([script, "--rate-limits", alpha_cfg, "--agent", "alpha",
                    "--account", ADA, "--ledger", led, "--append", "--now", str(t)])

    decisions = []
    for i, (t, five) in enumerate(((T0, 50), (T0 + 1800, 70), (T0 + 3600, 85))):
        rc, out, _ = sweep(t, five)
        appended = (out or {}).get("ledger", {}).get("rows_appended")
        control("sweep %d reached its subject (appended 2 rows)" % (i + 1), appended, 2)
        session = [l for l in (out or {}).get("limits", []) if l["name"] == "Current session"]
        decisions.append((rc, session[0]["decision"] if session else None))
    ok("three sweeps: first-reading, watch, then switch-projection (exit 1 = trigger)",
       decisions, [(0, "first-reading"), (0, "watch"), (1, "switch-projection")])

    m = mutant(tmp, "one-check", PARSE, 'TRIPPED_BEFORE = ("watch", "switch-projection")',
               "TRIPPED_BEFORE = ()")
    led2 = os.path.join(tmp, "agents-mutant.md")
    shutil.copy(ledger, led2)
    # replay the same three sweeps on a fresh ledger copy with the rule removed
    with open(led2, "w", encoding="utf-8") as fh:
        fh.write(pu.LEDGER_PREAMBLE)
    mres = [sweep(t, f, script=m, led=led2)[0] for t, f in ((T0, 50), (T0 + 1800, 70), (T0 + 3600, 85))]
    control("with the two-check rule removed the third sweep is NOT a trigger - "
            "the scenario can see the rule", mres[2], 0)

    rc1, pick1, _ = run(P + ["--agent", "alpha", "--current", ADA, "--auth", "token",
                             "--now", str(T0 + 3700)])
    rc2, pick2, _ = run(P + ["--agent", "alpha", "--current", ADA, "--auth", "token",
                             "--now", str(T0 + 3700)])
    control("the pick READ the ledger (ada carries a reading time)",
            [a for a in (pick1 or {}).get("accounts", []) if a["username"] == ADA][0]["reading_at"]
            if pick1 else None, "2026-10-16T13:00Z")
    ok("the picker names the OTHER account", (rc1, (pick1 or {}).get("pick")), (0, GRACE))
    ok("...deterministically: the same inputs give the same pick and reason",
       ((pick2 or {}).get("pick"), (pick2 or {}).get("reason")),
       ((pick1 or {}).get("pick"), (pick1 or {}).get("reason")))
    m = mutant(tmp, "current-not-excluded", PICK, "        if user == current:\n",
               "        if False:\n", extra=("parse_usage.py",),
               more=(("        elif hs:\n", "        elif False:\n"),))
    control("with the account the agent is on (current, and leased to it) no longer "
            "excluded the pick is ada itself - the scenario can see those rules",
            run([m, "--config", cfg, "--agent", "alpha", "--current", ADA, "--auth", "token",
                 "--now", str(T0 + 3700)])[1]["pick"], ADA)

    auth_file = os.path.join(tmp, "alpha-home", "claude-auth.env")
    os.makedirs(os.path.dirname(auth_file), mode=0o700)
    rc, took, _ = run(P + ["--take", GRACE, "--agent", "alpha", "--install-token", auth_file,
                           "--why", "Current session switch-projection, resets 4:00pm (UTC)",
                           "--now", str(T0 + 4000)])
    ok("--take grace --install-token -> exit 0, ada released",
       (rc, (took or {}).get("taken"), (took or {}).get("released")), (0, GRACE, [ADA]))
    ok("the lease moved: grace is alpha's and ada is free",
       sorted((u, l["agent"]) for u, l in json.load(open(leases)).items()), [(GRACE, "alpha")])
    ok("the agent's auth file is grace's token, byte for byte",
       open(auth_file, "rb").read() == open(entries[GRACE]["token_file"], "rb").read(), True)
    ok("...and it is 0600", mode(auth_file), 0o600)
    ok("the take created the handover ledger", os.path.isfile(handover), True)
    rows = [l for l in (open(handover, encoding="utf-8") if os.path.isfile(handover) else [])
            if l.startswith("| 2026")]
    ok("the handover ledger records the move: old ada, new grace, why, lease change",
       rows[-1].split(" | ")[1:5] if rows else None,
       ["alpha", ADA, GRACE, "Current session switch-projection, resets 4:00pm (UTC)"])
    ok("...with the outcome naming what was released and taken",
       "lease moved: released ada@example.com, took grace@example.com" in (rows[-1] if rows else ""),
       True)
    m = mutant(tmp, "token-0644", PICK, "replace_file(install_to, tfh.read(), 0o600)",
               "replace_file(install_to, tfh.read(), 0o644)", extra=("parse_usage.py",))
    dest2 = os.path.join(tmp, "alpha-home", "mutant-auth.env")
    lease_copy = os.path.join(tmp, "leases-copy.json")
    shutil.copy(leases, lease_copy)
    run([m, "--config", cfg, "--leases", lease_copy, "--take", GRACE, "--agent", "alpha",
         "--install-token", dest2])
    control("a copy that installs the token 0644 is caught by the mode check",
            mode(dest2) == 0o600 if os.path.exists(dest2) else None, False)

    # install-token refusals change NOTHING
    snap = (open(leases, "rb").read(), open(auth_file, "rb").read())
    os.chmod(entries[ADA]["token_file"], 0o644)
    rc, out, _ = run(P + ["--take", ADA, "--agent", "alpha", "--install-token", auth_file])
    ok("a token file readable by others is refused, and nothing changed",
       (rc, "readable by others" in (out or {}).get("reason", ""),
        (open(leases, "rb").read(), open(auth_file, "rb").read()) == snap), (1, True, True))
    os.chmod(entries[ADA]["token_file"], 0o600)
    forged = os.path.join(secrets, "forged.env")
    with open(forged, "w", encoding="utf-8") as fh:
        fh.write("# fleet-auth: token\n# fleet-account: %s\nCLAUDE_CODE_OAUTH_TOKEN=x\n" % GRACE)
    os.chmod(forged, 0o600)
    raw = json.load(open(pool))
    raw[0]["token_file"] = forged
    forged_pool = os.path.join(secrets, "forged-pool.json")
    with open(forged_pool, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    rc, out, _ = run(P + ["--pool", forged_pool, "--take", ADA, "--agent", "alpha",
                          "--install-token", auth_file])
    ok("a token file whose header names ANOTHER account is refused, nothing changed",
       (rc, (open(leases, "rb").read(), open(auth_file, "rb").read()) == snap), (1, True))
    rc, out, _ = run(P + ["--take", ADA, "--agent", "beta"])
    ok("--take of an account leased to nobody by another agent works; alpha's stays",
       (rc, json.load(open(leases))[GRACE]["agent"]), (0, "alpha"))
    rc, out, _ = run(P + ["--record", "--agent", "alpha", "--account", GRACE,
                          "--why", "handover resumed", "--outcome", "working, package read"])
    ok("--record appends a row that moves no lease",
       (rc, (open(handover, encoding="utf-8").read() if os.path.isfile(handover) else "").rstrip().endswith(
           "| alpha | grace@example.com | grace@example.com | handover resumed | working, package read |")),
       (0, True))

    # ------------------------------------------- 3. leases never double-assign
    GATE = r"""
import os, sys, time
ready, gate = sys.argv[1], sys.argv[2]
open(os.path.join(ready, str(os.getpid())), "w").close()
deadline = time.monotonic() + 60
while not os.path.exists(gate):
    if time.monotonic() > deadline:
        sys.exit(97)
    time.sleep(0.0005)
os.execv(sys.executable, [sys.executable] + sys.argv[3:])
"""

    def race(script, tag):
        work = os.path.join(tmp, "race-" + tag)
        os.mkdir(work)
        ready, gate = os.path.join(work, "ready"), os.path.join(work, "gate")
        os.mkdir(ready)
        lf, hl = os.path.join(work, "leases.json"), os.path.join(work, "handover.md")
        with open(lf, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        agents = ["racer%02d" % i for i in range(RACERS)]
        procs = [(a, subprocess.Popen(
            [sys.executable, "-c", GATE, ready, gate, script, "--config", cfg, "--leases", lf,
             "--handover-ledger", hl, "--take", ADA, "--agent", a],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)) for a in agents]
        deadline = time.monotonic() + 60
        while len(os.listdir(ready)) < len(agents) and time.monotonic() < deadline:
            time.sleep(0.005)
        open(gate, "w").close()
        res = []
        for a, p in procs:
            o, e = p.communicate(timeout=120)
            outputs.append(o + e)
            try:
                res.append((a, p.returncode, json.loads(o)))
            except ValueError:
                res.append((a, p.returncode, None))
        winners = [r for r in res if r[1] == 0]
        final = json.load(open(lf)).get(ADA, {}).get("agent")
        took_rows = [l for l in open(hl, encoding="utf-8") if "took ada@example.com" in l] \
            if os.path.exists(hl) else []
        return res, winners, final, took_rows

    res, winners, final, took_rows = race(PICK, "real")
    print("    race(real take): %d racers, %d winner(s) %s, exit codes %s"
          % (len(res), len(winners), [w[0] for w in winners], sorted(r[1] for r in res)))
    control("every racer reported a result", len([r for r in res if r[2] is not None]), RACERS)
    ok("the real take: exactly one winner", len(winners), 1)
    ok("...the lease file names that winner", final, winners[0][0] if winners else "?")
    ok("...every loser was refused naming the winner",
       all(r[1] == 1 and ("leased to %s" % final) in (r[2] or {}).get("reason", "")
           for r in res if r not in winners), True)
    ok("...and the handover ledger has ONE row for the take", len(took_rows), 1)
    naive = mutant(tmp, "no-lock", PICK, "    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n",
                   "    pass\n", extra=("parse_usage.py",))
    src = open(naive, encoding="utf-8").read()
    # The sleep goes between the take's READ of the leases and everything after it;
    # the replacement is built from the anchor so the two cannot drift apart.
    widen = "        leases = read_leases(lease_path)\n"
    anchor = widen + "        hs = holders"
    control("the naive copy's widening sleep applies exactly once", src.count(anchor), 1)
    with open(naive, "w", encoding="utf-8") as fh:
        fh.write(src.replace(anchor, anchor.replace(
            widen, widen + "        __import__('time').sleep(0.5)\n")))
    nres, nwin, _, _ = race(naive, "naive")
    print("    CONTROL race(no lock, 0.5 s window): %d racers, %d winner(s), exit codes %s"
          % (len(nres), len(nwin), sorted(r[1] for r in nres)))
    if len(nwin) <= 1:
        for r in nres[:2]:
            print("      racer %s exit %d: %s" % (r[0], r[1], (r[2] or {}).get("reason") or (r[2] or {}).get("fault")))
    control("the naive racers all reported", len([r for r in nres if r[2] is not None]), RACERS)
    control("NEGATIVE CONTROL: the same harness sees MORE than one winner without the lock",
            len(nwin) > 1, True)

    # ------------------------------------------------ 4. the ledger round-trips
    rows = pu.read_ledger_rows(ledger, "alpha")
    last = [r for r in rows if r["window_name"] == "Current session"][-1]
    ok("the last session row reads back as written: time, account, %, decision",
       (last["time"], last["account"], last["percent"], last["decision"]),
       ("2026-10-16T13:00Z", ADA, "85", "switch-projection"))
    ok("...its velocity (30.0 %/h) and projected depletion (13:30Z) read back",
       (last["velocity"], last["projected_depletion"]), ("30.0", "2026-10-16T13:30Z"))
    week = [r for r in rows if r["window_name"] == "Current week (all models)"][-1]
    ok("a reset written in the screen's shape resolves back to the snapshot's instant",
       (pu.resolve_reset(last["resets"], T0 + 3600), pu.resolve_reset(week["resets"], T0 + 3600)),
       (float(five_reset), float(seven_reset)))
    ok("...and the weekly row classifies LONG, the session row SHORT (the picker's rule)",
       (pu.classify_window(week["resets"]), pu.classify_window(last["resets"])), ("long", "short"))
    m = mutant(tmp, "no-minutes", PARSE,
               '    return "%d:%02d%s" % (dt.hour % 12 or 12, dt.minute, "am" if dt.hour < 12 else "pm")',
               '    return "%d%s" % (dt.hour % 12 or 12, "am" if dt.hour < 12 else "pm")')
    mpu_dir = os.path.dirname(m)
    sys.path.insert(0, mpu_dir)
    spec = importlib.util.spec_from_file_location("pu_mutant", m)
    mpu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mpu)
    odd = T0 + 37 * 60
    control("a reset written without its minutes no longer round-trips",
            mpu.resolve_reset(mpu.format_reset(odd, "short"), T0) == float(odd), False)
    ok("the real writer round-trips an off-the-hour reset",
       pu.resolve_reset(pu.format_reset(odd, "short"), T0), float(odd))

    # ---------------------------------------- 5. snapshot route and its writer
    empty_cfg = os.path.join(tmp, "no-snapshot")
    os.mkdir(empty_cfg)
    lb = open(ledger, "rb").read()
    rc, out, _ = run([PARSE, "--rate-limits", empty_cfg, "--agent", "alpha", "--account", GRACE,
                      "--ledger", ledger, "--append", "--now", str(T0)])
    ok("NO snapshot is inconclusive (exit 3), appends nothing - never ok",
       (rc, (out or {}).get("verdict"), open(ledger, "rb").read() == lb), (3, "inconclusive", True))
    with open(os.path.join(empty_cfg, pu.SNAPSHOT_NAME), "w") as fh:
        fh.write("{not json")
    ok("a snapshot that is not JSON is an instrument fault (exit 2)",
       run([PARSE, "--rate-limits", empty_cfg, "--floor-only", "--now", str(T0)])[0], 2)
    snapshot(empty_cfg, 92, 10, T0 + 3600, seven_reset)
    rc, out, _ = run([PARSE, "--rate-limits", empty_cfg, "--floor-only", "--now", str(T0)])
    ok("a session window at 92% from a snapshot trips the floor (exit 1)",
       (rc, [l["decision"] for l in (out or {}).get("limits", [])]), (1, ["switch-floor", "floor-only"]))
    snapshot(empty_cfg, 92, 97, T0 - 60, T0 - 86400)
    rc, out, _ = run([PARSE, "--rate-limits", empty_cfg, "--floor-only", "--now", str(T0)])
    ok("windows whose resets have PASSED read 0%; the weekly reset rolls a week forward",
       [(l["percent"], l["resets"]) for l in (out or {}).get("limits", [])],
       [(0, "-"), (0, "Oct 22, 12:00pm (UTC)")])

    sl_cfg = os.path.join(tmp, "statusline-cfg")
    os.mkdir(sl_cfg)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=sl_cfg)
    feed = {"rate_limits": {"five_hour": {"used_percentage": 41.4, "resets_at": T0 + 3600},
                            "seven_day": {"used_percentage": 10, "resets_at": seven_reset}}}
    p = subprocess.run([sys.executable, STATUS], input=json.dumps(feed), capture_output=True,
                       text=True, env=env)
    ok("the status line prints both windows and exits 0", (p.returncode, p.stdout.strip()),
       (0, "5h 41% | 7d 10%"))
    snap_path = os.path.join(sl_cfg, pu.SNAPSHOT_NAME)
    ok("...and writes the snapshot parse_usage reads",
       json.load(open(snap_path))["rate_limits"]["five_hour"]["used_percentage"], 41.4)
    feed2 = {"rate_limits": {"seven_day": {"used_percentage": 12, "resets_at": seven_reset}}}
    subprocess.run([sys.executable, STATUS], input=json.dumps(feed2), capture_output=True,
                   text=True, env=env)
    kept = json.load(open(snap_path))["rate_limits"]
    ok("a window missing from the next input is KEPT with its last reading",
       (kept["five_hour"]["used_percentage"], kept["seven_day"]["used_percentage"]), (41.4, 12))
    p = subprocess.run([sys.executable, STATUS], input="garbage", capture_output=True,
                       text=True, env=env)
    ok("garbage on stdin never fails the status line (exit 0, nothing printed)",
       (p.returncode, p.stdout, p.stderr), (0, "", ""))
    rc, out, _ = run([PARSE, "--rate-limits", sl_cfg, "--floor-only", "--now", str(T0)])
    ok("parse_usage reads the writer's own file", [l["percent"] for l in (out or {}).get("limits", [])],
       [41, 12])

    # ------------------------------------------- no credential in any output
    secrets_seen = list(TOKENS.values()) + [PASSWORD]
    control("the scan looks for the credentials that were registered",
            all(s in (open(entries[ADA]["token_file"]).read() + open(entries[GRACE]["token_file"]).read()
                      + open(pool).read()) for s in secrets_seen), True)
    control("the scan has outputs to search", len(outputs) >= 30, True)
    leaked = sorted({s[:16] for s in secrets_seen for o in outputs if s in o})
    ok("no token or password reaches stdout or stderr on any path", leaked, [])
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
