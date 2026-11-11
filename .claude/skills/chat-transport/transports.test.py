#!/usr/bin/env python3
"""Guard for the transport registry and the placeholder transports.

Run: python3 transports.test.py   (from any directory; offline, writes nothing)

What it pins:
  - every `.claude/skills/*/transport.json` in this fleet tree loads through
    fleetlib.transports, and `working()` is exactly the working ones;
  - each descriptor's id patterns accept the shape they name and refuse a near
    miss, so a pattern that matches everything (or nothing) reds here before
    claim.py or the scheduler trusts it;
  - Slack's descriptor carries the names the live daemons are keyed on, and its
    follower filter passes and drops what slack-communication's SKILL.md says it
    does;
  - each placeholder's watch.py refuses with the WATCH-GUARD line and exit 2,
    with nothing on stdout;
  - every transport skill's SKILL.md carries every outbound heading, and a
    placeholder's says "Not implemented in this version." under each.

THREE OUTCOMES, never two - the last line says which:
    0  ALL CHECKS PASSED
    1  FAILED - a check found a defect
    3  NO VERDICT - the registry was never reached (fleetlib did not import, or
       the directory scan found no descriptor at all), so no check below could
       have measured anything; an empty registry would otherwise pass the
       per-descriptor loops vacuously.

The descriptors are counted twice on purpose: once by globbing the skill
directories here, once through fleetlib. A loader that silently skipped a
descriptor (a bad one, a renamed key) would still hand back a registry that
"loads"; comparing the two name sets is what reds that, so do not replace the
glob with the loader's own answer.
"""
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
FLEET_ROOT = os.path.dirname(os.path.dirname(SKILLS))
HEADINGS = ["Post", "Reply in thread", "React", "Direct message", "Upload a file",
            "Fetch a message", "Permalink"]
PLACEHOLDER_TEXT = "Not implemented in this version."

_failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


def no_verdict(why):
    print(f"\nNO VERDICT: {why}")
    sys.exit(3)


# --- reached: the registry, counted two ways ---------------------------------
on_disk = {}
for p in sorted(glob.glob(os.path.join(SKILLS, "*", "transport.json"))):
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    on_disk[d.get("name")] = {"skill": os.path.basename(os.path.dirname(p)), "desc": d}
if not on_disk:
    no_verdict(f"no .claude/skills/*/transport.json under {SKILLS}")

sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
# The subject is THIS tree's registry: FLEET_TRANSPORTS_DIR (a fleetlib test seam)
# would point the loader at a fixture registry and the two counts would disagree.
os.environ.pop("FLEET_TRANSPORTS_DIR", None)
try:
    from fleetlib import transports  # noqa: E402
    loaded = transports.all()
    working = transports.working()
except Exception as e:  # noqa: BLE001 - a registry that cannot load is the finding
    check("the registry loads through fleetlib.transports", False, f"{type(e).__name__}: {e}")
    print(f"\nFAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)


def _names(got):
    items = got.values() if isinstance(got, dict) else got
    return sorted(d["name"] for d in items)


check("every transport.json on disk loads through fleetlib.transports, and nothing else does",
      _names(loaded) == sorted(on_disk), f"loaded={_names(loaded)} on disk={sorted(on_disk)}")
want_working = sorted(n for n, v in on_disk.items() if v["desc"].get("status") == "working")
check("working() is exactly the descriptors whose status is working",
      _names(working) == want_working and want_working, f"working={_names(working)} want={want_working}")
# A status is a claim about the watcher: a working transport runs a real watcher,
# a placeholder runs the shared refusal. A descriptor flipped to `working` over the
# placeholder watcher would get a unit rendered for a watcher that only refuses.
PLACEHOLDER_WATCH = os.path.join(HERE, "placeholder_watch.py")
for n, v in sorted(on_disk.items()):
    script = os.path.realpath(os.path.join(SKILLS, v["skill"], v["desc"].get("watch", {}).get("script", "")))
    is_stub = script == os.path.realpath(PLACEHOLDER_WATCH)
    check(f"{n}: status {v['desc'].get('status')!r} agrees with its watcher",
          os.path.isfile(script) and is_stub == (v["desc"].get("status") == "placeholder"),
          f"watch script resolves to {script}")
for n in on_disk:
    try:
        got = transports.get(n)
        ok = got["name"] == n
    except Exception as e:  # noqa: BLE001
        ok, got = False, f"{type(e).__name__}: {e}"
    check(f"get({n!r}) returns that transport's descriptor", ok, f"got={got!r}"[:200])

# --- id patterns: each accepts its shape and refuses a near miss --------------
SAMPLES = {
    "slack": {"user": (["U0ADA12", "UABCDEFG"], ["u0ada12", "W0ADA12", "U0AD"]),
              "conversation": (["C0GENRL", "D0DMADA", "G0PRIV"], ["U0ADA12", "c0genrl", "C", "C0X/../y"]),
              "message": (["1700000000.123456", "999999999.000001"],
                          ["1700000000.12345", "1700000000", "1700000000.123456\n"])},
    "discord": {"user": (["123456789012345678"], ["12345", "abc456789012345678"]),
                "conversation": (["123456789012345678"], ["-123456789012345678"]),
                "message": (["12345678901234567890"], ["123456789012345678901"])},
    "telegram": {"user": (["12345"], ["1234", "-12345"]),
                 "conversation": (["-1001234567", "123456"], ["--1001234567", "1234"]),
                 "message": (["42", "1"], ["0x2a", "1234567890123"])},
}
for n, v in sorted(on_disk.items()):
    ids = v["desc"].get("ids", {})
    if n not in SAMPLES:
        check(f"{n}: has id samples in this test", False,
              "a new transport needs accept/refuse samples here before its patterns are trusted")
        continue
    for key, (good, bad) in SAMPLES[n].items():
        rx = re.compile(ids.get(key, "(?!)"))
        check(f"{n}: ids.{key} accepts {good} and refuses {bad}",
              all(rx.fullmatch(s) for s in good) and not any(rx.fullmatch(s) for s in bad),
              f"pattern={ids.get(key)!r}")

# --- Slack: the names the live daemons are keyed on, and the follower filter --
slack = on_disk.get("slack", {}).get("desc", {})
check("slack: the descriptor lives in slack-communication",
      on_disk.get("slack", {}).get("skill") == "slack-communication")
check("slack: watch names equal the live daemon's (watch.py, slack-watch, SLACK_WATCH_CONFIG, SLACK)",
      (slack.get("watch", {}).get("script"), slack.get("watch", {}).get("job"),
       slack.get("watch", {}).get("config_env"), slack.get("line_prefix"), slack.get("status"))
      == ("watch.py", "slack-watch", "SLACK_WATCH_CONFIG", "SLACK", "working"),
      f"watch={slack.get('watch')} line_prefix={slack.get('line_prefix')}")
flt = re.compile(slack.get("watch", {}).get("follow_include", "(?!)"))
PASS = ["SLACK #general message [ts 1700000000.000001] Ada (U0ADA): hi",
        "SLACK DM message [ts 1700000000.000002] Grace (U0GRACE): hi",
        "DAEMON-BACKLOG 40 lines while no follower was armed",
        "DAEMON-ALERT agent-slack-watch@ada is not active",
        "WATCH-GUARD another watcher already holds the lock; not watching",
        "WATCH-INFO retired #ops (C0OPS): Slack says channel_not_found",
        "Traceback (most recent call last):",
        "WATCH-ERROR discovery HTTPError: HTTP Error 429: Too Many Requests",
        "WATCH-ERROR dm-discovery HTTPError: HTTP Error 429: Too Many Requests",
        "WATCH-ERROR #general TimeoutError: timed out",
        "WATCH-ERROR sweep #general SlackApiError: conversations.history: channel_not_found"]
DROP = ["WATCH-ERROR #general HTTPError: HTTP Error 429: Too Many Requests",
        "WATCH-ERROR sweep DM D0ADA HTTPError: HTTP Error 429: Too Many Requests",
        "some unrelated line"]
check("slack: the follower filter passes every line SKILL.md says it does",
      all(flt.search(ln) for ln in PASS), f"dropped={[ln for ln in PASS if not flt.search(ln)]}")
check("slack: the follower filter drops a per-conversation or sweep 429, and noise",
      not any(flt.search(ln) for ln in DROP), f"passed={[ln for ln in DROP if flt.search(ln)]}")

# --- placeholders: descriptor, watcher, headings -----------------------------
placeholders = sorted(n for n, v in on_disk.items() if v["desc"].get("status") == "placeholder")
check("there is at least one placeholder transport to measure", bool(placeholders), f"{placeholders}")
env = {k: v for k, v in os.environ.items() if not k.endswith("_WATCH_CONFIG")}
for n in placeholders:
    d, skill = on_disk[n]["desc"], on_disk[n]["skill"]
    pfx = d.get("line_prefix", "")
    pflt = re.compile(d.get("watch", {}).get("follow_include", "(?!)"))
    check(f"{n}: follower filter passes its own lines and the guard line",
          bool(pflt.search(f"{pfx} #general message [ts 1] x"))
          and bool(pflt.search(f"WATCH-GUARD {n} transport is a placeholder: not implemented"))
          and not pflt.search("SLACK #general message [ts 1] x"), f"filter={pflt.pattern!r}")
    script = os.path.join(SKILLS, skill, d.get("watch", {}).get("script", "watch.py"))
    want = f"WATCH-GUARD {n} transport is a placeholder: not implemented"
    for argv in ([], ["--once"]):
        r = subprocess.run([sys.executable, script, *argv], capture_output=True, text=True,
                           env=env, timeout=30)
        check(f"{n}: watch.py {' '.join(argv) or '(no args)'} exits 2 with the WATCH-GUARD line only",
              (r.returncode, r.stdout, r.stderr.strip()) == (2, "", want),
              f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr.strip()!r}")
    r = subprocess.run([sys.executable, script, "--bogus"], capture_output=True, text=True,
                       env=env, timeout=30)
    check(f"{n}: watch.py with an unknown argument is a usage error (exit 2, nothing on stdout)",
          r.returncode == 2 and r.stdout == "" and "usage" in r.stderr, f"rc={r.returncode} err={r.stderr!r}")

for n, v in sorted(on_disk.items()):
    path = os.path.join(SKILLS, v["skill"], "SKILL.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        check(f"{n}: {v['skill']}/SKILL.md is readable", False, f"{type(e).__name__}: {e}")
        continue
    missing = [h for h in HEADINGS if not re.search(rf"^#{{2,4}} {re.escape(h)}\s*$", text, re.M)]
    check(f"{n}: SKILL.md carries every outbound heading", not missing, f"missing={missing}")
    if v["desc"].get("status") == "placeholder":
        unsaid = [h for h in HEADINGS
                  if not re.search(rf"^#{{2,4}} {re.escape(h)}\s*\n\s*{re.escape(PLACEHOLDER_TEXT)}",
                                   text, re.M)]
        check(f"{n}: every heading of the placeholder says it is not implemented", not unsaid,
              f"headings without {PLACEHOLDER_TEXT!r}: {unsaid}")

print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
