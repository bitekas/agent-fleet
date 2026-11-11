#!/usr/bin/env python3
"""compact - type a command into the agent's OWN session from a process that outlives the turn.

An agent cannot type `/compact` into its own prompt from inside a turn: the turn is
the thing that is running, and a command typed into the input box while it runs is
queued, not executed. The only actor that can drive that prompt is one that is still
alive after the turn ends. This script spawns it: a fully detached sender that waits
`--delay` seconds - long enough for the agent's turn to finish - and then types the
message into the agent's tmux pane and presses Enter.

THE SECOND SEND, AND WHY THE SESSION NEEDS IT

The same sender then waits `--wake-delay` seconds more and types a second line, the wake
line (`--wake-message`), followed by its own Enter. A compaction's output is a local
command record, not a user turn: once it finishes, the session sits idle at its prompt
and no turn runs. Nothing else wakes it - after the compaction its monitors are stopped
(SKILL.md section 5) - so without the wake line "the first turn after the compaction",
where the agent re-reads its charter and re-arms its watchers, never happens, and the
session stays idle until something outside it types into the pane. The wake line is
ordinary text, so it starts an ordinary turn. `--no-wake` drops it.

WHAT "DETACHED" HAS TO MEAN HERE, AND WHAT IT DELIBERATELY DOES NOT

Ending a turn signals the turn's children, so the sender must not be one of them. It
is double-forked, `setsid`-ed into its own session and process group, has its stdio
pointed at /dev/null and ignores SIGHUP; the parent reports its pid and exits at once.
That breaks the process TREE, which is the only boundary that matters here.

It does NOT break the cgroup, and it must not try to. An agent session runs as a
systemd service with `KillMode=control-group`, so a service restart kills everything
the session spawned regardless of `setsid`. Escaping that cgroup would be pointless
AND wrong: the tmux session this sender types into is inside the same cgroup, so a
restart takes the target away too. A sender that survived it would type into nothing, or worse, into
whatever reclaimed the pane. Surviving the TURN is the requirement; surviving the
SERVICE is not.

NO CREDENTIALS ARE INVOLVED, AND NONE ARE ACCEPTED

The caller's own environment is the credential. `$TMUX` names the socket the caller is
already connected to and `$TMUX_PANE` identifies its pane, so `display-message` answers
"which session am I in" without anything being passed in. `$TMUX_TMPDIR` is the
fallback for a caller outside tmux. There is no key, token or path to hand over, and
this script never reads one.

Usage (<skill dir> is the directory holding this file):
  <skill dir>/compact.py                   # /compact in 3 s, then the wake line 120 s later
  <skill dir>/compact.py --no-wake         # /compact only
  <skill dir>/compact.py --dry-run         # print what would be sent, spawn nothing
  <skill dir>/compact.py --message ping --delay 3
  <skill dir>/compact.py --wake-message "<the install's own wake text>"
  <skill dir>/compact.py --socket <path> --target <session>:<window> --message ping

Exit codes: 0 sender spawned (or dry run printed), 2 refused with one line saying why.
"""
import argparse
import os
import signal
import subprocess
import sys
import time

DEFAULT_MESSAGE = "/compact"
DEFAULT_DELAY = 3.0
# The wake line names the re-arm first because it is the one whose absence is silent: a
# session whose monitors are not armed looks idle, not broken. Which monitors those are
# is the install's business, so the default defers to the charter, and an install with
# its own wording passes it with --wake-message (its CONTEXT.md carries the text).
DEFAULT_WAKE_MESSAGE = (
    "Compaction done. First: re-arm the monitors your charter names. "
    "Then re-read your charter and the agent rules, pick up what you were holding, "
    "and stand by.")
DEFAULT_WAKE_DELAY = 120.0
TMUX = "tmux"


class Refusal(Exception):
    """Refuse to spawn, with one line the caller can act on. Exit code 2."""


def _run(argv):
    """Run a tmux command. Returns (rc, stdout, stderr), all stripped."""
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def socket_path(env, uid, socket=None, tmpdir=None):
    """Resolve the tmux socket, most explicit source first.

    `$TMUX` is `<socket>,<pid>,<pane index>`; its first field is the socket the caller
    is already talking to, which is the one answer that cannot be wrong. A socket dir
    (`--tmpdir` or `$TMUX_TMPDIR`) holds `tmux-<uid>/default`, which is where tmux puts
    the default server for that user.
    """
    if socket:
        return socket
    if tmpdir:
        return os.path.join(tmpdir, "tmux-%d" % uid, "default")
    tmux_var = env.get("TMUX", "")
    if tmux_var:
        return tmux_var.split(",")[0]
    env_tmpdir = env.get("TMUX_TMPDIR", "")
    if env_tmpdir:
        return os.path.join(env_tmpdir, "tmux-%d" % uid, "default")
    return None


def _check_text(flag, text):
    """The refusals every typed line obeys, named by the flag that supplied it."""
    if not text:
        raise Refusal("refusing: %s is empty, there is nothing to send" % flag)
    if "\n" in text or "\r" in text:
        raise Refusal(
            "refusing: %s contains a newline, which submits the line early "
            "and sends the remainder as a second prompt" % flag)


def resolve(message, delay, socket=None, tmpdir=None, target=None,
            env=None, uid=None, run=None, wake_message=None, wake_delay=0.0):
    """Resolve socket and target, or raise Refusal. Every check performs a real call.

    `wake_message=None` means no wake line is sent, so it is not checked.

    Nothing here asks whether a path exists. A socket file can be present and belong to
    a dead server, and `os.path.exists` is green on both, so the server is probed by
    asking it a question (`display-message`) and the session by asking it to be found
    (`has-session`). The failure line then carries tmux's own error text.
    """
    env = os.environ if env is None else env
    uid = os.getuid() if uid is None else uid
    # Looked up at CALL time, not bound as a default: a default argument freezes the
    # module-level name at def time, and the test's stub then never runs - which the
    # test cannot tell apart from a stub that runs and agrees.
    run = _run if run is None else run

    _check_text("--message", message)
    if delay < 0:
        raise Refusal("refusing: --delay is negative")
    if wake_message is not None:
        _check_text("--wake-message", wake_message)
        if wake_delay < 0:
            raise Refusal("refusing: --wake-delay is negative")

    # ⚠️ THERE IS DELIBERATELY NO SUBAGENT GUARD HERE, AND RE-ADDING ONE ON AN
    # ENVIRONMENT VARIABLE IS A REGRESSION. A subagent inherits its parent's $TMUX, so
    # the session it resolves is the PARENT's pane and compacting from one discards the
    # context of a session that is mid-turn waiting for that subagent to return. That
    # hazard is real; what does not exist is a measured way to detect it from here.
    # MEASURED 2026-09-12, BOTH SIDES, which is the only reading that settles it:
    #   subagent turn   CLAUDE_CODE_CHILD_SESSION=1
    #   root turn       CLAUDE_CODE_CHILD_SESSION=1   (read in the pane-owning session's
    #                                                  own shell, not inferred from it)
    # So the variable marks a Bash tool call, not a subagent, and a guard keyed on it
    # refuses the ONE caller it exists to serve: the session that owns the pane. It
    # shipped that way for exactly one commit. The earlier "root leaves it unset" reading
    # came from /proc/<claude pid>/environ, which holds the process's EXEC-TIME
    # environment and never the per-tool-call variables the harness injects - a subagent
    # inferring a fact about its parent instead of measuring it there.
    # CLAUDE_CODE_SESSION_ID and CLAUDE_CODE_BRIDGE_SESSION_ID are not a substitute: they
    # are different namespaces (a local uuid and the hosted session id), so they differ
    # in the root turn too.
    # The protection is therefore the RULE, stated in SKILL.md and in the agent skill:
    # only the session that owns the pane runs this. A guard whose discriminator has not
    # been read on both sides is worse than no guard, because it is trusted.

    sock = socket_path(env, uid, socket=socket, tmpdir=tmpdir)
    if not sock:
        raise Refusal(
            "refusing: cannot resolve a tmux socket - $TMUX and $TMUX_TMPDIR are both "
            "unset and neither --socket nor --tmpdir was given")

    rc, own, err = run([TMUX, "-S", sock, "display-message", "-p", "#S:#I"])
    if rc != 0 or not own:
        raise Refusal(
            "refusing: no tmux server answered on %s (%s)" % (sock, err or "no output"))
    own_session = own.split(":")[0]

    inside_tmux = bool(env.get("TMUX")) and not socket and not tmpdir
    if target:
        if inside_tmux and target.split(":")[0] != own_session:
            raise Refusal(
                "refusing: --target %s is not this session (%s). This script types into "
                "the caller's own pane and nobody else's." % (target, own))
    elif inside_tmux:
        target = own
    else:
        # Outside tmux there is no $TMUX_PANE to disambiguate, so display-message
        # answered with whichever session the server considers current. That is only
        # trustworthy when there is exactly one.
        rc, out, err = run([TMUX, "-S", sock, "list-sessions", "-F", "#S"])
        if rc != 0:
            raise Refusal("refusing: cannot list sessions on %s (%s)" % (sock, err))
        sessions = [s for s in out.splitlines() if s]
        if len(sessions) != 1:
            raise Refusal(
                "refusing: not running inside tmux and the server on %s has %d sessions "
                "(%s) - pass --target <session>:<window>"
                % (sock, len(sessions), ", ".join(sessions) or "none"))
        target = own

    rc, _, err = run([TMUX, "-S", sock, "has-session", "-t", target.split(":")[0]])
    if rc != 0:
        raise Refusal("refusing: target session %s is not on %s (%s)" % (target, sock, err))

    return {"socket": sock, "target": target, "own": own}


def sender_argv(sock, target, message):
    """The two tmux calls the detached sender makes, in order.

    ⚠️ `--` is load-bearing, not decoration. Measured on tmux 3.6: without it a message
    beginning with a dash is parsed as flags - `send-keys -l "-bar"` dies with
    `unknown flag -b` and NOTHING is typed, while the caller sees a spawned pid and
    assumes delivery. `-l` keeps tmux from interpreting the text as key names, so
    `/compact` goes in as eight characters rather than as a key sequence.

    Enter is a SEPARATE call: `-l` makes every argument literal, so an `Enter` in the
    same call would type the word.
    """
    return (
        [TMUX, "-S", sock, "send-keys", "-t", target, "-l", "--", message],
        [TMUX, "-S", sock, "send-keys", "-t", target, "Enter"],
    )


def sender_steps(sock, target, message, delay, wake_message=None, wake_delay=0.0):
    """Everything the sender does, in order: a list of (wait seconds, text argv, Enter argv).

    Each wait is measured from the end of the step before it, so the wake line goes in
    `wake_delay` seconds after the compaction message was submitted. `wake_message=None`
    leaves the wake step out.
    """
    steps = [(delay, ) + sender_argv(sock, target, message)]
    if wake_message is not None:
        steps.append((wake_delay, ) + sender_argv(sock, target, wake_message))
    return steps


def spawn_detached(steps):
    """Double-fork the sender and return its pid, read back through a pipe.

    `steps` is `sender_steps()`'s list. ONE process performs every step in sequence, so
    the wake line can never overtake the message it follows.

    The intermediate child calls setsid() and forks again, so the grandchild is not a
    session leader and can never acquire a controlling terminal. The parent reaps the
    intermediate child immediately, so no zombie is left behind, and learns the
    grandchild's pid through the pipe because it never forked it itself.
    """
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid > 0:
        os.close(write_fd)
        os.waitpid(pid, 0)
        with os.fdopen(read_fd) as r:
            child_pid = r.read().strip()
        return int(child_pid) if child_pid else 0

    # intermediate child
    try:
        os.close(read_fd)
        os.setsid()
        grandchild = os.fork()
        if grandchild > 0:
            os.write(write_fd, str(grandchild).encode())
            os.close(write_fd)
            os._exit(0)

        # grandchild: the sender
        os.close(write_fd)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        for wait, argv_text, argv_enter in steps:
            time.sleep(wait)
            subprocess.call(argv_text)
            subprocess.call(argv_enter)
    except BaseException:
        os._exit(1)
    os._exit(0)


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="compact.py",
        description="Send a command to the agent's own tmux pane from a detached "
                    "process that outlives the current turn.")
    p.add_argument("--message", default=DEFAULT_MESSAGE,
                   help="text to type (default: %s)" % DEFAULT_MESSAGE)
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help="seconds to wait before typing (default: %g)" % DEFAULT_DELAY)
    p.add_argument("--wake-message", default=DEFAULT_WAKE_MESSAGE,
                   help="line typed after the message, which starts the first turn "
                        "(default: %s)" % DEFAULT_WAKE_MESSAGE)
    p.add_argument("--wake-delay", type=float, default=DEFAULT_WAKE_DELAY,
                   help="seconds between the message and the wake line "
                        "(default: %g)" % DEFAULT_WAKE_DELAY)
    p.add_argument("--no-wake", action="store_true",
                   help="send the message only, no wake line")
    p.add_argument("--socket", help="tmux socket path (default: from $TMUX)")
    p.add_argument("--tmpdir", help="tmux socket dir (default: from $TMUX_TMPDIR)")
    p.add_argument("--target", help="tmux target <session>:<window> (default: this pane's)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the resolved target and commands, spawn nothing")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    wake_message = None if args.no_wake else args.wake_message
    try:
        r = resolve(args.message, args.delay, socket=args.socket, tmpdir=args.tmpdir,
                    target=args.target, wake_message=wake_message,
                    wake_delay=args.wake_delay)
    except Refusal as e:
        print(str(e), file=sys.stderr)
        return 2

    steps = sender_steps(r["socket"], r["target"], args.message, args.delay,
                         wake_message, args.wake_delay)
    if args.dry_run:
        print("socket:  %s" % r["socket"])
        print("target:  %s" % r["target"])
        print("message: %s" % args.message)
        print("delay:   %gs" % args.delay)
        if wake_message is None:
            print("wake:    none (--no-wake)")
        else:
            print("wake:    %s" % wake_message)
            print("wake delay: %gs after the message" % args.wake_delay)
        for i, (wait, argv_text, argv_enter) in enumerate(steps, 1):
            print("send %d, %gs after the %s:" % (i, wait, "spawn" if i == 1 else "send before it"))
            print("  %s" % " ".join(argv_text))
            print("  %s" % " ".join(argv_enter))
        print("dry run: nothing spawned")
        return 0

    pid = spawn_detached(steps)
    print("sender pid %d: types %r into %s on %s in %gs"
          % (pid, args.message, r["target"], r["socket"], args.delay))
    if wake_message is not None:
        print("wake line: types %r %gs after the message"
              % (wake_message, args.wake_delay))
    return 0


if __name__ == "__main__":
    sys.exit(main())
