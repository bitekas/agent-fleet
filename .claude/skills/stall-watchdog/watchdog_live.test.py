#!/usr/bin/env python3
"""watchdog_live.test.py - the real watchdog.py against a real tmux pane.

watchdog.test.py drives the decision logic offline; this drives the whole loop on
both Linux and macOS: a private tmux server (its socket under a short /tmp
directory, inside macOS's 104-byte socket limit), a pane that draws a REAL captured
confirmation prompt (fixtures/real-prompt-a.txt) and then records every byte typed
into it in raw mode, and the real watchdog.py with stall_secs 2 polling it.

  fires    the prompt pane receives Escape (the refusal) and then the configured
           notice, in that order.
  control  the SAME prompt with the session's idle footer drawn under it (an agent
           that merely PRINTED a chooser) receives nothing in the same time. Its
           silence means something only because `fires`, on the same text without
           the footer, was answered: the idle exclusion is what decides.

Exit codes: 0 both hold; 1 a case failed; 3 NO VERDICT (no tmux, or the pane never
showed the prompt, so nothing below could be about the watchdog).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
WATCHDOG = os.path.join(HERE, "watchdog.py")
FIXTURE = os.path.join(HERE, "fixtures", "real-prompt-a.txt")
# A pane program: draw a file, then log every byte typed into the pane, raw.
PANE = r"""import os, sys, tty
sys.stdout.write(open(sys.argv[1], encoding="utf-8").read())
sys.stdout.flush()
tty.setraw(0)
with open(sys.argv[2], "ab", buffering=0) as log:
    while True:
        b = os.read(0, 1)
        if not b:
            break
        log.write(b)
"""
UTF8 = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def wait_for(pred, secs, step=0.2):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def main():
    tmux = shutil.which("tmux")
    if not tmux:
        print("NO VERDICT: tmux is not on PATH")
        return 3
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="wdl.", dir="/tmp"))
    run = os.path.join(tmp, "run")
    os.makedirs(run)
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env.update(TMUX_TMPDIR=run, LC_ALL=UTF8, LANG=UTF8)
    with open(os.path.join(HERE, "config.example.json"), encoding="utf-8") as f:
        base = json.load(f)
    notice = base["action"]["notice"]
    pane_py = os.path.join(tmp, "pane.py")
    with open(pane_py, "w") as f:
        f.write(PANE)
    with open(FIXTURE, encoding="utf-8") as f:
        prompt = f.read()
    idle = os.path.join(tmp, "idle.txt")
    with open(idle, "w", encoding="utf-8") as f:
        # The footer is the pane's LAST row, as a live session draws it: no newline
        # after it, and the pane exactly as tall as the text (session() below), because
        # the exclusion reads the bottom idle_tail_lines rows and blank rows count.
        f.write(prompt.rstrip("\n") + "\n\n" + "-" * 60 + "\n> \n" + "-" * 60 + "\n  esc to interrupt")
    with open(idle, encoding="utf-8") as f:
        idle_rows = len(f.read().splitlines())

    def tm(*args):
        return subprocess.run([tmux, "-u", *args], env=env, capture_output=True, text=True, timeout=30)

    def session(name, text, rows=50):
        log = os.path.join(tmp, f"{name}.keys")
        open(log, "wb").close()
        r = tm("new-session", "-d", "-s", name, "-x", "200", "-y", str(rows),
               f"{sys.executable} {pane_py} {text} {log}")
        return log, r

    def watchdog(name):
        cfg = json.loads(json.dumps(base))
        cfg["tmux"] = {"tmpdir": run, "target": f"{name}:0"}
        cfg["stall"]["stall_secs"] = 2
        cfg["stall"]["poll_secs"] = 0.5
        cfg["state"]["dir"] = os.path.join(tmp, f"state-{name}")
        cfg["owner"]["claude_config_dir"] = None
        os.makedirs(cfg["state"]["dir"])
        path = os.path.join(tmp, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        out = open(os.path.join(tmp, f"{name}.log"), "w")
        return subprocess.Popen([sys.executable, WATCHDOG], env=dict(env, STALL_WATCHDOG_CONFIG=path),
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=tmp)

    def keys(log):
        with open(log, "rb") as f:
            return f.read()

    procs = []
    try:
        fire_log, r1 = session("fire", FIXTURE)
        idle_log, r2 = session("idle", idle, idle_rows)
        shown = wait_for(lambda: "Do you want to proceed?" in tm("capture-pane", "-p", "-t", "fire:0").stdout
                         and tm("capture-pane", "-p", "-t", "idle:0").stdout.rstrip("\n")
                         .endswith("esc to interrupt"), 10)
        if r1.returncode or r2.returncode or not shown:
            print(f"NO VERDICT: the panes never showed the prompt ({r1.stderr.strip()} {r2.stderr.strip()})")
            return 3
        print("[PASS] control: both panes show the captured prompt; the idle one ends in the idle footer")
        procs = [watchdog("fire"), watchdog("idle")]
        fired = wait_for(lambda: notice[:40].encode() in keys(fire_log), 25)
        got = keys(fire_log)
        check("fires: the prompt pane received Escape, then the notice",
              fired and got.startswith(b"\x1b") and got.index(b"\x1b") < got.index(notice[:40].encode()),
              repr(got[:80]))
        time.sleep(1.0)
        check("control: the same prompt under the idle footer received nothing", keys(idle_log) == b"",
              repr(keys(idle_log)[:80]))
    finally:
        for p in procs:
            p.kill()
            p.wait()
        tm("kill-server")
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): " + "; ".join(_failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
