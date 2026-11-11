#!/usr/bin/env python3
"""Regression guard for compact.py: target resolution, the refusals, the exact argv,
the two sends (the message, then the wake line), the dry run, and the detach itself.

Offline. No tmux server is contacted for the resolution cases - every tmux call goes
through an injected `run` stub, so this exercises the decisions rather than tmux. The
one case that spawns a real process (section 6) runs `/bin/sh`, not tmux, for the same
reason: what is under test there is the double fork, not key delivery.

Section 3 carries a REGRESSION PIN against a guard that was here and was wrong: nothing
in resolution may be gated on an environment variable. Its reasoning is beside the case.

⚠️ TWO CONTROLS HOLD THIS FILE UP. Neither is decorative, and removing either leaves a
suite that passes while measuring nothing:

  1. THE HEALTHY-PATH CASE (section 1). Most of this file asserts that `resolve()`
     REFUSES. A `resolve()` that raised Refusal unconditionally - a stray typo in the
     first guard, a renamed argument - would turn every one of those green at once.
     Section 1 is what makes the refusals mean "refused for this reason" instead of
     "refused". If section 1 fails, no refusal result below carries any information.
     It resolves once with the wake line ON, because the wake-line refusals in section
     3 lean on it the same way; and every wake-line refusal also asserts that it names
     `--wake-message`, so a refusal of the MAIN message cannot stand in for it.
  2. THE ARGV EQUALITY (sections 5 and 6). It compares the whole list, not a membership
     or a substring. `--` is what stops tmux parsing a message that begins with a dash
     as flags (measured on tmux 3.6: `send-keys -l "-bar"` dies `unknown flag -b` and
     types nothing), and a `in`-style assertion cannot see it removed. The same
     whole-list equality covers the sender's step list - both sends, their order and
     their waits - because the wake line is the only thing that starts a turn after the
     compaction, and a step list that silently lost it would still contain `/compact`.

Run: python3 <skill dir>/compact.test.py   (exits nonzero on any failure)
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compact.py")
_spec = importlib.util.spec_from_file_location("compact_mod", _SCRIPT)
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)

_failures = []


def check(name, cond, detail=""):
    if cond:
        print("ok   %s" % name)
    else:
        print("FAIL %s%s" % (name, ("  [%s]" % detail) if detail else ""))
        _failures.append(name)


def fake_tmux(sessions=("claude-agent", ), current="claude-agent:0", answer_rc=0):
    """A tmux stand-in. Records the argv it is handed, answers the three calls
    resolve() makes: display-message, list-sessions, has-session."""
    calls = []

    def run(argv):
        calls.append(argv)
        if "display-message" in argv:
            return (answer_rc, current if answer_rc == 0 else "", "" if answer_rc == 0
                    else "no server running")
        if "list-sessions" in argv:
            return (0, "\n".join(sessions), "")
        if "has-session" in argv:
            want = argv[argv.index("-t") + 1]
            return (0, "", "") if want in sessions else (1, "", "can't find session: %s" % want)
        raise AssertionError("unexpected tmux call: %r" % (argv, ))

    run.calls = calls
    return run


def refusal(**kw):
    """Call resolve() with defaults filled in; return the Refusal text, or None."""
    kw.setdefault("message", "/compact")
    kw.setdefault("delay", 3.0)
    kw.setdefault("env", {})
    kw.setdefault("uid", 1000)
    kw.setdefault("run", fake_tmux())
    try:
        c.resolve(**kw)
        return None
    except c.Refusal as e:
        return str(e)


def resolved(**kw):
    kw.setdefault("message", "/compact")
    kw.setdefault("delay", 3.0)
    kw.setdefault("env", {})
    kw.setdefault("uid", 1000)
    kw.setdefault("run", fake_tmux())
    return c.resolve(**kw)


SOCK = "/run/claude-tmux-agent/tmux-1000/default"
INSIDE = {"TMUX": "%s,1533747,0" % SOCK}

# --- 1. CONTROL: the healthy path resolves ------------------------------------------
# Read the banner at the top of this file before touching this section.
r = resolved(env=INSIDE)
check("CONTROL: a session inside tmux resolves its own socket and pane",
      r == {"socket": SOCK, "target": "claude-agent:0", "own": "claude-agent:0"}, repr(r))
r = resolved(env=INSIDE, wake_message=c.DEFAULT_WAKE_MESSAGE,
             wake_delay=c.DEFAULT_WAKE_DELAY)
check("CONTROL: the same resolution with the default wake line ON",
      r == {"socket": SOCK, "target": "claude-agent:0", "own": "claude-agent:0"}, repr(r))

# --- 2. Socket resolution, most explicit source first --------------------------------
check("socket comes from $TMUX's first field, not the whole variable",
      c.socket_path(INSIDE, 1000) == SOCK)
check("socket falls back to $TMUX_TMPDIR/tmux-<uid>/default",
      c.socket_path({"TMUX_TMPDIR": "/run/claude-tmux-agent"}, 1000) == SOCK)
check("the uid is the CALLER's, not a hardcoded 1000",
      c.socket_path({"TMUX_TMPDIR": "/run/d"}, 501) == "/run/d/tmux-501/default")
check("--socket beats every environment source",
      c.socket_path(INSIDE, 1000, socket="/tmp/x/s") == "/tmp/x/s")
check("--tmpdir beats $TMUX",
      c.socket_path(INSIDE, 1000, tmpdir="/tmp/d") == "/tmp/d/tmux-1000/default")
check("nothing to resolve from returns None rather than guessing",
      c.socket_path({}, 1000) is None)

r = resolved(env={"TMUX_TMPDIR": "/run/claude-tmux-agent"})
check("resolution from $TMUX_TMPDIR alone reaches the single live session",
      r["socket"] == SOCK and r["target"] == "claude-agent:0", repr(r))

r = resolved(env=INSIDE, socket="/tmp/ctest/s", target="probe:0",
             run=fake_tmux(sessions=("probe", ), current="probe:0"))
check("explicit --socket + --target address another server",
      r == {"socket": "/tmp/ctest/s", "target": "probe:0", "own": "probe:0"}, repr(r))

r = resolved(env=INSIDE, target="claude-agent:1")
check("a --target in the caller's OWN session is accepted",
      r["target"] == "claude-agent:1", repr(r))

# --- 3. Refusals ---------------------------------------------------------------------
m = refusal(env={})
check("no $TMUX, no $TMUX_TMPDIR, no override: refuses",
      m is not None and "cannot resolve a tmux socket" in m, repr(m))

m = refusal(env=INSIDE, target="claude-other:0",
            run=fake_tmux(sessions=("claude-agent", "claude-other")))
check("a --target in ANOTHER session is refused (this types into its own pane only)",
      m is not None and "is not this session" in m, repr(m))

m = refusal(env=INSIDE, message="")
check("an empty message is refused", m is not None and "nothing to send" in m, repr(m))

m = refusal(env=INSIDE, message="ping\nrm -rf /")
check("a message carrying a newline is refused (it would submit early and send the rest)",
      m is not None and "newline" in m, repr(m))

m = refusal(env=INSIDE, delay=-1)
check("a negative delay is refused", m is not None and "negative" in m, repr(m))

m = refusal(env=INSIDE, wake_message="", wake_delay=90.0)
check("an empty wake message is refused, naming --wake-message",
      m is not None and "--wake-message" in m and "nothing to send" in m, repr(m))

m = refusal(env=INSIDE, wake_message="post-compaction\nrm -rf /", wake_delay=90.0)
check("a wake message carrying a newline is refused, naming --wake-message",
      m is not None and "--wake-message" in m and "newline" in m, repr(m))

m = refusal(env=INSIDE, wake_message="wake\r", wake_delay=90.0)
check("a wake message carrying a carriage return is refused",
      m is not None and "--wake-message" in m and "newline" in m, repr(m))

m = refusal(env=INSIDE, wake_message="wake", wake_delay=-1)
check("a negative wake delay is refused",
      m is not None and "--wake-delay is negative" in m, repr(m))

m = refusal(env=INSIDE, wake_message=None, wake_delay=-1)
check("with no wake line (--no-wake) the wake delay is not checked", m is None, repr(m))

m = refusal(env=INSIDE, run=fake_tmux(answer_rc=1))
check("a socket no server answers on is refused, carrying tmux's own error",
      m is not None and "no tmux server answered" in m and "no server running" in m, repr(m))

m = refusal(env=INSIDE, target="claude-agent:0",
            run=fake_tmux(sessions=("someone-else", ), current="claude-agent:0"))
check("a target whose session the server cannot find is refused",
      m is not None and "is not on" in m, repr(m))

m = refusal(env={"TMUX_TMPDIR": "/run/claude-tmux-agent"},
            run=fake_tmux(sessions=("a", "b"), current="a:0"))
check("outside tmux with several sessions and no --target: refuses as ambiguous",
      m is not None and "2 sessions" in m, repr(m))

# ⚠️ REGRESSION PIN, NOT A NICETY: no environment variable may gate resolution.
# CLAUDE_CODE_CHILD_SESSION was once read here as a subagent marker. MEASURED
# 2026-09-12 on both sides, it is set to 1 in a SUBAGENT turn and set to 1 in the
# ROOT turn as well (read in the pane-owning session's own shell), so it marks a Bash
# tool call rather than a subagent, and the guard keyed on it refused the one caller
# the script exists to serve. This case fails the moment such a guard comes back. The
# hazard it was aimed at is real and is handled by the RULE in SKILL.md - only the
# session that owns the pane runs this - because no discriminator has been read on
# both sides. Do not re-add one without both readings.
# Caught rather than left to raise: a re-added guard must come back as a NAMED failure,
# not as a traceback that stops the file before the sections below it ever run.
try:
    _marked = resolved(env=dict(INSIDE, CLAUDE_CODE_CHILD_SESSION="1"))
except c.Refusal as _e:
    _marked = {"target": "REFUSED: %s" % _e}
check("no environment marker gates resolution (CLAUDE_CODE_CHILD_SESSION is set in the "
      "ROOT turn too, so a guard on it refuses the pane owner)",
      _marked["target"] == "claude-agent:0", repr(_marked))

# --- 4. The order of the probes ------------------------------------------------------
# Each check performs a real operation rather than a stat: the server is asked a
# question and the session is asked to be found. A path-existence check would be green
# on a socket file left behind by a dead server.
run = fake_tmux()
resolved(env=INSIDE, run=run)
verbs = [a[3] for a in run.calls]
check("resolution probes by ASKING tmux: display-message then has-session",
      verbs == ["display-message", "has-session"], repr(verbs))

# --- 5. CONTROL: the exact argv the sender will run ----------------------------------
# Read the banner at the top of this file before touching this section.
text, enter = c.sender_argv(SOCK, "claude-agent:0", "/compact")
check("CONTROL: literal send is exact, with -l and the -- that protects a leading dash",
      text == ["tmux", "-S", SOCK, "send-keys", "-t", "claude-agent:0", "-l", "--",
               "/compact"], repr(text))
check("Enter is a SEPARATE call, and carries no -l (which would type the word)",
      enter == ["tmux", "-S", SOCK, "send-keys", "-t", "claude-agent:0", "Enter"],
      repr(enter))
text_dash, _ = c.sender_argv(SOCK, "claude-agent:0", "-bar")
check("a message beginning with a dash still lands after --, where tmux reads it as text",
      text_dash[-2:] == ["--", "-bar"], repr(text_dash))

T = "claude-agent:0"


def _send(msg):
    return ["tmux", "-S", SOCK, "send-keys", "-t", T, "-l", "--", msg]


_ENTER = ["tmux", "-S", SOCK, "send-keys", "-t", T, "Enter"]
steps = c.sender_steps(SOCK, T, "/compact", 3.0, "wake up", 90.0)
check("CONTROL: two steps, the message then the wake line, each with its own Enter "
      "and its own wait",
      steps == [(3.0, _send("/compact"), _ENTER), (90.0, _send("wake up"), _ENTER)],
      repr(steps))
steps = c.sender_steps(SOCK, T, "/compact", 3.0, None, 90.0)
check("no wake message: exactly one step", steps == [(3.0, _send("/compact"), _ENTER)],
      repr(steps))

# --- 6. The dry run prints and spawns nothing ----------------------------------------
_spawned = []
_real_spawn = c.spawn_detached
c.spawn_detached = lambda *a, **k: _spawned.append(a) or 4242
os.environ["TMUX"] = "%s,1,0" % SOCK
os.environ.pop("TMUX_TMPDIR", None)
# Set, not popped: the CLI path must run with the marker present, because that is
# what the pane-owning session's own shell carries.
os.environ["CLAUDE_CODE_CHILD_SESSION"] = "1"
_real_run = c._run
c._run = fake_tmux()

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = c.main(["--dry-run", "--message", "ping", "--delay", "7"])
out = buf.getvalue()
check("--dry-run exits 0", rc == 0, "rc=%r" % rc)
check("--dry-run prints socket, target, message and delay",
      SOCK in out and "claude-agent:0" in out and "ping" in out and "7s" in out, repr(out))
check("--dry-run prints all four commands of the two sends, the wake line second",
      out.count("send-keys") == 4
      and 0 <= out.find("-l -- ping") < out.find("-l -- " + c.DEFAULT_WAKE_MESSAGE)
      and "120s" in out, repr(out))
check("--dry-run spawns nothing", _spawned == [], repr(_spawned))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = c.main(["--dry-run", "--message", "ping", "--no-wake"])
out = buf.getvalue()
check("--dry-run --no-wake prints one send and no wake line",
      rc == 0 and out.count("send-keys") == 2 and c.DEFAULT_WAKE_MESSAGE not in out,
      repr(out))
check("--dry-run --no-wake spawns nothing either", _spawned == [], repr(_spawned))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = c.main(["--message", "ping", "--delay", "0"])
out = buf.getvalue()
check("a real run spawns the sender and reports its pid", rc == 0 and len(_spawned) == 1
      and "4242" in out, "rc=%r out=%r spawned=%r" % (rc, out, _spawned))
# The pid line and the wake line are two lines, and the second says when the wake line
# is typed: the caller reads that to know how long the session stays without a turn.
_out_lines = out.splitlines()
check("a real run prints the pid line, then one line saying when the wake line is typed",
      len(_out_lines) == 2 and _out_lines[0].startswith("sender pid 4242: ")
      and _out_lines[1] == "wake line: types %r 120s after the message"
      % c.DEFAULT_WAKE_MESSAGE, repr(out))
# CONTROL (banner, item 2): the defaults reach the sender. This is the CLI wiring - a
# default changed, or the wake step dropped between parse_args and spawn - which the
# sender_steps() equality in section 5 cannot see because it is handed its arguments.
check("CONTROL: by default the sender gets the message, then the default wake line "
      "after the default wake delay",
      _spawned[-1:] == [([(0.0, _send("ping"), _ENTER),
                          (c.DEFAULT_WAKE_DELAY, _send(c.DEFAULT_WAKE_MESSAGE), _ENTER)], )],
      repr(_spawned[-1:]))
check("the wake defaults are the documented ones",
      c.DEFAULT_WAKE_DELAY == 120.0 and c.DEFAULT_WAKE_MESSAGE
      == "Compaction done. First: re-arm the monitors your charter names. "
         "Then re-read your charter and the agent rules, pick up what you were holding, "
         "and stand by.",
      "%r %r" % (c.DEFAULT_WAKE_DELAY, c.DEFAULT_WAKE_MESSAGE))
# The default is GENERIC: it names no install's daemons, transport or units, because an
# install that has them passes its own text with --wake-message. A default that named
# one install's monitors would send every other install's agent looking for watchers it
# does not run, on the one turn that is supposed to restore its working state.
check("the default wake line names no transport or daemon of any one install",
      not any(w in c.DEFAULT_WAKE_MESSAGE.lower()
              for w in ("slack", "discord", "telegram", "scheduler", "daemon", "watcher")),
      c.DEFAULT_WAKE_MESSAGE)
# SKILL.md quotes the default so a reader knows what arrives without opening the script.
# A mirror nothing compares is a second copy that drifts, so it is compared here, with
# whitespace collapsed because the prose wraps inside the quotation.
with open(os.path.join(os.path.dirname(_SCRIPT), "SKILL.md"), encoding="utf-8") as _fh:
    _skill_text = " ".join(_fh.read().split())
check("SKILL.md quotes the default wake line verbatim",
      " ".join(c.DEFAULT_WAKE_MESSAGE.split()) in _skill_text, c.DEFAULT_WAKE_MESSAGE)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = c.main(["--message", "ping", "--delay", "0", "--wake-message", "go",
                 "--wake-delay", "5"])
check("--wake-message and --wake-delay reach the sender",
      rc == 0 and _spawned[-1:] == [([(0.0, _send("ping"), _ENTER),
                                      (5.0, _send("go"), _ENTER)], )],
      "rc=%r spawned=%r" % (rc, _spawned[-1:]))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = c.main(["--message", "ping", "--delay", "0", "--no-wake"])
check("--no-wake hands the sender the message alone",
      rc == 0 and _spawned[-1:] == [([(0.0, _send("ping"), _ENTER)], )],
      "rc=%r spawned=%r" % (rc, _spawned[-1:]))
check("--no-wake prints the pid line alone",
      len(buf.getvalue().splitlines()) == 1 and "wake line" not in buf.getvalue(),
      repr(buf.getvalue()))

_n = len(_spawned)
buf = io.StringIO()
err = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
    rc = c.main(["--wake-message", "a\nb"])
check("a wake-message refusal exits 2, names --wake-message, and spawns nothing",
      rc == 2 and "--wake-message" in err.getvalue() and len(_spawned) == _n,
      "rc=%r err=%r" % (rc, err.getvalue()))

buf = io.StringIO()
err = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
    rc = c.main(["--message", ""])
check("a refusal exits 2 and says why on stderr",
      rc == 2 and "nothing to send" in err.getvalue(), "rc=%r err=%r" % (rc, err.getvalue()))

c.spawn_detached = _real_spawn
c._run = _real_run

# --- 7. The detach itself, with a real process ---------------------------------------
# tmux is not involved: a python one-liner appends a tag and the time to a marker file.
# What is under test is that the parent returns IMMEDIATELY, that the sender is in its
# own session (so the signal sent to the turn's process group cannot reach it), that
# ONE process runs all four commands in order, and that the wake step really waits its
# own delay after the first step. A sleep is a lower bound, so the gap check cannot
# flake on a slow machine; it reds only if the wait is skipped or misapplied.
tmp = tempfile.mkdtemp(prefix="compact-test-")
marker = os.path.join(tmp, "marker")


def _tag(t):
    return [sys.executable, "-c",
            "import time; open(%r, 'a').write('%s %%f\\n' %% time.time())" % (marker, t)]


WAKE_GAP = 1.0
pid = c.spawn_detached([(0.6, _tag("text"), _tag("enter")),
                        (WAKE_GAP, _tag("wake"), _tag("wake-enter"))])
check("spawn_detached returns a plausible pid", pid > 1, "pid=%r" % pid)
check("the parent returns BEFORE the delay elapses", not os.path.exists(marker))
# setsid() runs in the INTERMEDIATE child, so the sender is in a new session without
# being its leader - which is the point of the second fork: a non-leader can never
# acquire a controlling terminal. What matters is that neither identifier is shared
# with the caller, because that is what a signal to the turn's process group follows.
check("the sender is outside the caller's session and process group",
      os.getsid(pid) != os.getsid(0) and os.getpgid(pid) != os.getpgid(0),
      "sender sid=%r pgid=%r / caller sid=%r pgid=%r"
      % (os.getsid(pid), os.getpgid(pid), os.getsid(0), os.getpgid(0)))


def _lines():
    if not os.path.exists(marker):
        return []
    return [ln.split() for ln in open(marker).read().splitlines() if ln]


deadline = time.time() + 20
while time.time() < deadline and len(_lines()) < 4:
    time.sleep(0.2)
got = _lines()
tags = [ln[0] for ln in got]
check("the sender ran all four commands, in order, after the delay",
      tags == ["text", "enter", "wake", "wake-enter"], repr(got))
if len(got) == 4:
    gap = float(got[2][1]) - float(got[1][1])
    check("the wake line waited its own delay after the first Enter",
          gap >= WAKE_GAP * 0.95, "gap=%.3fs, wanted >= %.2fs" % (gap, WAKE_GAP))
else:
    check("the wake line waited its own delay after the first Enter", False,
          "the sender did not run all four commands, so the gap cannot be measured")
shutil.rmtree(tmp, ignore_errors=True)

print()
if _failures:
    print("FAILED: %d check(s): %s" % (len(_failures), ", ".join(_failures)))
    sys.exit(1)
print("ALL CHECKS PASSED")
