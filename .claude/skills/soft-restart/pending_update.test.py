#!/usr/bin/env python3
"""Regression guard for pending_update.py: the banner's position, the session process,
the running and installed versions, the verdict table, and the CLI's lines and codes.

Offline. No tmux server, no `ps`, no /proc and no claude binary is touched: every
command goes through an injected `run` stub and /proc through an injected `readlink`,
so this exercises the decisions rather than the machine.

The fixtures are pane captures. `pane-banner.txt` is lines 38-54 of agent-revive's
`working-panel-scroll-prose.txt` and `pane-no-banner.txt` its `idle-after-api-error.txt`,
both byte-exact (synthetic transcript text in the real layout). `pane-menu.txt` is its
`auth-method-prompt.txt`, a selection menu whose cursor is the input box's glyph.
`pane-banner-quoted.txt` is built by hand: the banner's exact words twice, as a grep
result and as a right-aligned line, neither on the line above the input box's rule.

TWO CONTROLS HOLD THIS FILE UP:

  1. THE HEALTHY PATH (section 1): the banner fixture, a stale running binary and a
     newer installed one read PENDING with exit 0. Most cases below assert NONE or NO
     VERDICT; a measure() that never returned PENDING would turn every one of them green
     at once. If section 1 fails, nothing else here carries information.
  2. THE QUOTED BANNER (section 2) against the real one: the same words, the same
     right alignment, one line further from the rule, must read as no banner. A matcher
     that searched the whole pane would pass every other banner case and fail only this
     one, and that matcher reads a restart into any session that has quoted the banner.

Run: python3 <skill dir>/pending_update.test.py   (exits nonzero on any failure)
"""
import contextlib
import importlib.util
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("pending_update_mod",
                                               os.path.join(HERE, "pending_update.py"))
pu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pu)

_failures = []


def check(name, cond, detail=""):
    if cond:
        print("ok   %s" % name)
    else:
        print("FAIL %s%s" % (name, ("  [%s]" % (detail, )) if detail != "" else ""))
        _failures.append(name)


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


ENV = {"TMUX": "/tmp/fx-sock/default,4242,0", "TMUX_PANE": "%3"}
PS_HEALTHY = ("    1     0 systemd\n"
              " 4242     1 tmux: server\n"
              " 4300  4242 bash\n"
              " 4301  4300 claude\n"
              " 4400  4301 bash\n")
VERSIONS = "/x/.local/share/claude/versions/"


def machine(pane="pane-banner.txt", ps=PS_HEALTHY, pane_pid="4300",
            exe=VERSIONS + "2.1.286" + pu.DELETED, installed="2.1.323 (Claude Code)\n",
            capture_rc=0, version_rc=0, lsof=None):
    """Stubs for one fake machine. Returns (run, readlink, calls)."""
    calls = []
    text = fixture(pane) if pane else ""

    def run(argv):
        calls.append(argv)
        if argv[0] == pu.TMUX and "capture-pane" in argv:
            return (capture_rc, text if capture_rc == 0 else "", "" if capture_rc == 0
                    else "no server running")
        if argv[0] == pu.TMUX and "display-message" in argv:
            return (0, pane_pid + "\n", "")
        if argv[0] == "ps":
            return (0, ps, "")
        if argv[0] == "lsof":
            return (0, lsof, "") if lsof is not None else (1, "", "no such process")
        if argv[-1] == "--version":
            return (version_rc, installed if version_rc == 0 else "", "" if version_rc == 0
                    else "command not found")
        raise AssertionError("unexpected command: %r" % (argv, ))

    def readlink(path):
        calls.append(["readlink", path])
        if exe is None:
            raise OSError(13, "Permission denied")
        return exe

    return run, readlink, calls


def measured(has_proc=True, env=ENV, claude="claude", **kw):
    run, readlink, calls = machine(**kw)
    code, lines = pu.measure(env=env, run=run, readlink=readlink, has_proc=has_proc,
                             claude=claude)
    return code, lines, calls


# ---- 1. healthy path: the control every other case leans on --------------------------
code, lines, calls = measured()
check("1 banner + stale binary -> exit 0", code == 0, code)
check("1 the verdict line, whole",
      lines[-1] == "PENDING: running 2.1.286, installed 2.1.323, banner shown - "
                   "a restart adopts 2.1.323", lines[-1])
check("1 the running line names the pid and the deleted executable",
      "running:   2.1.286 (pid 4301, %s2.1.286 (deleted))" % VERSIONS in lines, lines)
check("1 reads the caller's own pane on the caller's own socket",
      ["tmux", "-S", "/tmp/fx-sock/default", "capture-pane", "-p", "-t", "%3"] in calls, calls)
check("1 reads /proc for the session process, not the pane's shell",
      ["readlink", "/proc/4301/exe"] in calls, calls)

# ---- 2. the banner is read on its line only --------------------------------------------
check("2 pane-banner.txt: shown", pu.banner_shown(fixture("pane-banner.txt")) is True)
check("2 pane-no-banner.txt: not shown", pu.banner_shown(fixture("pane-no-banner.txt")) is False)
check("2 CONTROL pane-banner-quoted.txt: the same words off the line are not the banner",
      pu.banner_shown(fixture("pane-banner-quoted.txt")) is False)
check("2 the quoted fixture does carry the exact words (the control can fire)",
      fixture("pane-banner-quoted.txt").count(pu.BANNER) == 2)
for name in ("pane-menu.txt", ):
    try:
        pu.banner_shown(fixture(name))
        check("2 %s: a menu is unreadable, not 'not shown'" % name, False, "no Unmeasured")
    except pu.Unmeasured as e:
        check("2 %s: a menu is unreadable, not 'not shown'" % name, "no box rule" in str(e), e)
try:
    pu.banner_shown("a screen with no input box\n")
    check("2 no input box -> unreadable", False, "no Unmeasured")
except pu.Unmeasured as e:
    check("2 no input box -> unreadable", "no input box" in str(e), e)

# ---- 3. the verdict table --------------------------------------------------------------
TABLE = [
    # (banner, running, installed, exit, prefix)
    (True, "2.1.286", "2.1.323", 0, "PENDING: "),
    (False, "2.1.323", "2.1.323", 1, "NONE: "),
    (True, "2.1.323", "2.1.323", 3, "NO VERDICT: the banner is shown but"),
    (False, "2.1.286", "2.1.323", 3, "NO VERDICT: the running binary is older"),
    (False, "2.1.324", "2.1.323", 3, "NO VERDICT: the running binary is NEWER"),
    (True, "2.1.324", "2.1.323", 3, "NO VERDICT: the running binary is NEWER"),
    (True, "2.1.99", "2.1.100", 0, "PENDING: "),   # numeric, not string, order
]
for banner, running, installed, want, prefix in TABLE:
    code, line = pu.decide(banner, running, installed)
    check("3 banner=%s running=%s installed=%s -> %d" % (banner, running, installed, want),
          code == want and line.startswith(prefix), (code, line))

code, lines, _ = measured(pane="pane-no-banner.txt", exe=VERSIONS + "2.1.323")
check("3 end to end: no banner, current binary -> NONE, exit 1",
      code == 1 and lines[-1].startswith("NONE: running 2.1.323, installed 2.1.323"), lines)
code, lines, _ = measured(pane="pane-banner-quoted.txt", exe=VERSIONS + "2.1.323")
check("3 end to end: a quoted banner over a current binary is NONE, not NO VERDICT",
      code == 1, lines)

# ---- 4. the session process -------------------------------------------------------------
table = pu.process_table(lambda argv: (0, PS_HEALTHY, ""))
check("4 the pane's shell -> its one claude child", pu.session_pid(4300, table) == 4301)
check("4 a pane whose own process is claude -> itself",
      pu.session_pid(4301, table) == 4301)
for label, ps in (("no claude child", " 4300  4242 bash\n 4310  4300 sleep\n"),
                  ("two claude children", " 4300  4242 bash\n 4301  4300 claude\n"
                                          " 4302  4300 claude\n")):
    code, lines, _ = measured(ps=ps)
    check("4 %s -> NO VERDICT naming the running leg" % label,
          code == 3 and lines[-1].startswith("NO VERDICT: running: the pane's process 4300 has"),
          lines[-1])
table = pu.process_table(lambda argv: (0, " 77  1 /x/.local/bin/claude\n", ""))
check("4 macOS ps prints a path as comm: matched by its basename",
      pu.session_pid(77, table) == 77)

# ---- 5. the running and installed versions ----------------------------------------------
check("5 ' (deleted)' is stripped before the version is read",
      pu.version_of_path(VERSIONS + "2.1.286 (deleted)") == "2.1.286")
check("5 a live executable reads the same", pu.version_of_path(VERSIONS + "2.1.323") == "2.1.323")
code, lines, _ = measured(exe="/usr/bin/node")
check("5 an executable not named for a version -> NO VERDICT",
      code == 3 and "is not named for a version" in lines[-1], lines[-1])
code, lines, _ = measured(exe=None)
check("5 an unreadable /proc entry -> NO VERDICT, with the errno text",
      code == 3 and "Permission denied" in lines[-1], lines[-1])
code, lines, calls = measured(has_proc=False,
                              lsof="p4301\nftxt\nn%s2.1.300\nftxt\nn/usr/lib/dyld\n" % VERSIONS)
check("5 no /proc: lsof's first txt entry is the executable",
      any(l.startswith("running:   2.1.300 (pid 4301") for l in lines)
      and not any(c[0] == "readlink" for c in calls), lines)
code, lines, _ = measured(has_proc=False)
check("5 no /proc and lsof fails -> NO VERDICT", code == 3 and "lsof" in lines[-1], lines[-1])
code, lines, _ = measured(version_rc=127)
check("5 claude --version fails -> NO VERDICT naming the installed leg",
      code == 3 and "installed: `claude --version` gave no version (command not found)"
      in lines[-1], lines[-1])
code, lines, _ = measured(installed="Claude Code\n")
check("5 a --version answer with no version -> NO VERDICT", code == 3, lines[-1])
_, _, calls = measured(claude="/opt/other/claude")
check("5 --claude names the client asked", ["/opt/other/claude", "--version"] in calls, calls)

# ---- 6. the pane, and the refusal -------------------------------------------------------
code, lines, _ = measured(capture_rc=1)
check("6 a failed capture is NO VERDICT on the banner leg, the others still read",
      code == 3 and lines[-1].startswith("NO VERDICT: banner: tmux capture-pane failed")
      and any(l.startswith("running:   2.1.286") for l in lines), lines)
code, lines, _ = measured(pane="pane-menu.txt")
check("6 a menu on screen is NO VERDICT, never NONE", code == 3, lines[-1])
for label, env in (("$TMUX unset", {"TMUX_PANE": "%3"}),
                   ("$TMUX_PANE unset", {"TMUX": "/tmp/fx-sock/default,1,0"})):
    try:
        pu.measure(env=env, run=machine()[0], readlink=machine()[1], has_proc=True)
        check("6 %s -> Refusal" % label, False, "no Refusal")
    except pu.Refusal as e:
        check("6 %s -> Refusal" % label, str(e).startswith("refusing: "), e)

# ---- 7. the CLI: codes, and the line printed last ----------------------------------------
def cli(**kw):
    run, readlink, _ = machine(**{k: v for k, v in kw.items() if k != "env"})
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pu.main([], env=kw.get("env", ENV), run=run, readlink=readlink, has_proc=True)
    return code, out.getvalue().splitlines(), err.getvalue()


code, out, _ = cli()
check("7 main: PENDING prints three readings then the verdict, exit 0",
      code == 0 and len(out) == 4 and out[-1].startswith("PENDING: "), out)
code, out, err = cli(env={})
check("7 main: refusal on stderr, exit 2", code == 2 and err.startswith("refusing: ") and not out,
      (code, out, err))


def boom(argv):
    raise RuntimeError("stub exploded")


o = io.StringIO()
with contextlib.redirect_stdout(o):
    code = pu.main([], env=ENV, run=boom, readlink=machine()[1], has_proc=True)
check("7 main: a crash inside measure is NO VERDICT with exit 3, never exit 1",
      code == 3 and o.getvalue().startswith("NO VERDICT: pending_update.py failed"), o.getvalue())

# ---- 8. SKILL.md's table names every verdict this prints --------------------------------
with open(os.path.join(HERE, "SKILL.md"), encoding="utf-8") as f:
    skill = f.read()
rows = dict(re.findall(r"^\| `(\d)` \| `([A-Z ]+:|refusing:) \.\.\.` \|", skill, re.M))
check("8 SKILL.md step 0's table: one row per exit code, each with its line",
      rows == {"0": "PENDING:", "1": "NONE:", "2": "refusing:", "3": "NO VERDICT:"}, rows)

if _failures:
    print("\n%d FAILED: %s" % (len(_failures), ", ".join(_failures)))
    sys.exit(1)
print("ALL CHECKS PASSED")
