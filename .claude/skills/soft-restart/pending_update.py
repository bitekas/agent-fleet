#!/usr/bin/env python3
"""pending_update - is a Claude Code update installed and waiting for THIS session to restart?

Step 0 of the soft-restart skill. It takes two readings, independently, and the verdict
needs both of them:

  THE BANNER. Once an update is installed under a running session, Claude Code draws
  `Update installed`, U+00B7, `Restart to update`, right-aligned on the line directly
  above the input box's top rule. This reads the caller's own pane and looks at that
  line only. The same words anywhere else on the screen are conversation text - a
  quoted fixture, the skill itself under discussion - and say nothing about the binary.

  THE BINARY. A running process keeps executing the file it was started from. An update
  installs the new version beside it and repoints the `claude` on PATH, which the running
  process never reads again. So the version the session RUNS is read from its process's
  executable - /proc/<pid>/exe on Linux, where a file the updater has since removed reads
  `<path> (deleted)`, and lsof's txt entry where there is no /proc - and the version
  INSTALLED is asked of the installed client itself, `claude --version`, which is the
  binary the service starts next.

WHY BOTH, AND WHY A DISAGREEMENT IS NO VERDICT RATHER THAN EITHER ANSWER

The banner is what the client says about itself; the executable is what the process is
actually running. A restart is worth its cost only when the two agree that something
newer is installed. A banner over a binary that is already the installed one means a
restart adopts nothing. A stale binary with no banner means the client and the process
disagree about what is installed, and that is a question for a person, not a reason for
an unattended exit. Each leg alone has a failure the other one catches.

WHICH PROCESS

The session's claude is the pane's own process, or that process's one `claude` child:
the fleet's units start the pane as `bash -lc 'claude --update; claude ... --continue ||
claude ...'`, so the pane process is the shell and the session is its child. Anything
else - no claude there, or two - is NO VERDICT, never a guess: the process this reads has
to be the one `/exit` ends.

Usage:
  pending_update.py                    # read this session's own pane and process
  pending_update.py --claude <command> # ask another installed client for its version

Exit codes and the LAST line printed:
  0  PENDING: ...     banner shown, running binary older than the installed one
  1  NONE: ...        no banner, running binary is the installed one
  2  refusing: ...    not inside tmux, so there is no own pane to read
  3  NO VERDICT: ...  the readings disagree, or one of them could not be taken

Exit 1 with no NONE line is Python failing to run this file, not an answer: read the
line, not the code.
"""
import argparse
import os
import re
import subprocess
import sys

TMUX = "tmux"
BANNER = "Update installed · Restart to update"
PROMPT = "❯"   # the glyph the input box's first line starts with
RULE = "─"     # the box-drawing line above and below the input box
DELETED = " (deleted)"
VERSION = re.compile(r"\d+(?:\.\d+)+")


class Refusal(Exception):
    """No own pane to read. Exit code 2."""


class Unmeasured(Exception):
    """A reading that could not be taken. The message says which and why."""


def _run(argv):
    """Run a command. Returns (rc, stdout, stderr); stdout is NOT stripped, because a
    pane capture's leading whitespace is part of what is being read."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True)
    except OSError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr.strip()


def own_pane(env):
    """The caller's tmux socket and pane, from the environment tmux gave it.

    `$TMUX` is `<socket>,<pid>,<session index>`; its first field is the socket the
    caller is already connected to. `$TMUX_PANE` is the caller's own pane id. Both are
    set in every shell an agent opens inside its pane, and a subagent inherits them,
    which is fine here: this only reads.
    """
    tmux_var, pane = env.get("TMUX", ""), env.get("TMUX_PANE", "")
    if not tmux_var or not pane:
        raise Refusal("refusing: $TMUX or $TMUX_PANE is unset - this is not running inside "
                      "a tmux pane, so there is no own pane and no session process to read")
    return tmux_var.split(",")[0], pane


def banner_shown(text):
    """True or False from the line above the input box's top rule; Unmeasured when the
    screen does not show an input box there (a dialog, a menu, a modal)."""
    lines = text.split("\n")
    prompts = [i for i, line in enumerate(lines) if line.lstrip().startswith(PROMPT)]
    if not prompts:
        raise Unmeasured("the pane shows no input box (no line starts with U+276F), so "
                         "the banner's line cannot be found - a dialog or menu may be open")
    i = prompts[-1]
    if i < 1 or not lines[i - 1].strip().startswith(RULE):
        raise Unmeasured("the last U+276F line on the pane has no box rule above it, so it "
                         "is not the input box - a selection menu may be open")
    above = lines[i - 2] if i >= 2 else ""
    return above.rstrip().endswith(BANNER)


def process_table(run):
    """{pid: (ppid, command basename)} from `ps`, in the form Linux and macOS both print."""
    rc, out, err = run(["ps", "-A", "-o", "pid=,ppid=,comm="])
    if rc != 0:
        raise Unmeasured("ps failed (%s)" % (err or "rc %d" % rc))
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2].strip()))
    return table


def session_pid(pane_pid, table):
    """The pane's own process when it is claude, else its one claude child."""
    if table.get(pane_pid, (None, ""))[1] == "claude":
        return pane_pid
    kids = sorted(pid for pid, (ppid, comm) in table.items()
                  if ppid == pane_pid and comm == "claude")
    if len(kids) != 1:
        raise Unmeasured("the pane's process %d has %d claude children (%s), so which one is "
                         "this session is not known" % (pane_pid, len(kids),
                                                         ", ".join(map(str, kids)) or "none"))
    return kids[0]


def executable(pid, run, readlink, has_proc):
    """The path of the file the process is executing, ` (deleted)` suffix kept."""
    if has_proc:
        try:
            return readlink("/proc/%d/exe" % pid)
        except OSError as e:
            raise Unmeasured("cannot read /proc/%d/exe (%s)" % (pid, e))
    rc, out, err = run(["lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"])
    names = [line[1:] for line in out.splitlines() if line.startswith("n")]
    if rc != 0 or not names:
        raise Unmeasured("lsof names no executable for pid %d (%s)" % (pid, err or "rc %d" % rc))
    return names[0]


def version_of_path(path):
    """The version a native install's executable is named for: `.../versions/<version>`."""
    name = os.path.basename(path[:-len(DELETED)] if path.endswith(DELETED) else path)
    if not VERSION.fullmatch(name):
        raise Unmeasured("the running executable %s is not named for a version, so this is "
                         "not the native install's layout and the running version cannot be "
                         "read from it" % path)
    return name


def installed_version(run, claude):
    rc, out, err = run([claude, "--version"])
    m = VERSION.match(out.strip()) if rc == 0 else None
    if not m:
        raise Unmeasured("`%s --version` gave no version (%s)"
                         % (claude, err or out.strip() or "rc %d" % rc))
    return m.group(0)


def as_tuple(version):
    return tuple(int(x) for x in version.split("."))


def decide(banner, running, installed):
    """(exit code, last line) from the two readings."""
    seen = "banner shown" if banner else "no banner"
    facts = "running %s, installed %s, %s" % (running, installed, seen)
    r, i = as_tuple(running), as_tuple(installed)
    if banner and r < i:
        return 0, "PENDING: %s - a restart adopts %s" % (facts, installed)
    if not banner and r == i:
        return 1, "NONE: %s - there is nothing to adopt" % facts
    if r > i:
        why = "the running binary is NEWER than the installed client"
    elif banner:
        why = "the banner is shown but the running binary is the installed one, so a restart adopts nothing"
    else:
        why = "the running binary is older than the installed client but no banner is shown"
    return 3, "NO VERDICT: %s - %s" % (why, facts)


def measure(env=None, run=None, readlink=None, has_proc=None, claude="claude"):
    """Take both readings and decide. Returns (exit code, lines to print)."""
    env = os.environ if env is None else env
    # Looked up at CALL time, not bound as defaults, so the test's stubs are the ones run.
    run = _run if run is None else run
    readlink = os.readlink if readlink is None else readlink
    has_proc = os.path.isdir("/proc/self") if has_proc is None else has_proc

    sock, pane = own_pane(env)
    out, problems = [], []

    banner = None
    rc, text, err = run([TMUX, "-S", sock, "capture-pane", "-p", "-t", pane])
    try:
        if rc != 0:
            raise Unmeasured("tmux capture-pane failed on %s (%s)" % (sock, err or "rc %d" % rc))
        banner = banner_shown(text)
        out.append("banner:    %s" % ("shown" if banner else "not shown"))
    except Unmeasured as e:
        problems.append("banner: %s" % e)
        out.append("banner:    unreadable")

    running = None
    try:
        rc, pane_pid, err = run([TMUX, "-S", sock, "display-message", "-p", "-t", pane,
                                 "#{pane_pid}"])
        if rc != 0 or not pane_pid.strip().isdigit():
            raise Unmeasured("tmux gave no pane pid for %s (%s)" % (pane, err or "rc %d" % rc))
        pid = session_pid(int(pane_pid.strip()), process_table(run))
        path = executable(pid, run, readlink, has_proc)
        running = version_of_path(path)
        out.append("running:   %s (pid %d, %s)" % (running, pid, path))
    except Unmeasured as e:
        problems.append("running: %s" % e)
        out.append("running:   unreadable")

    installed = None
    try:
        installed = installed_version(run, claude)
        out.append("installed: %s (%s --version)" % (installed, claude))
    except Unmeasured as e:
        problems.append("installed: %s" % e)
        out.append("installed: unreadable")

    if problems:
        out.append("NO VERDICT: %s" % "; ".join(problems))
        return 3, out
    code, line = decide(banner, running, installed)
    out.append(line)
    return code, out


def main(argv=None, **inject):
    p = argparse.ArgumentParser(
        prog="pending_update.py",
        description="Say whether a Claude Code update is installed and waiting for this "
                    "session to restart: the pane's banner and the running binary, both.")
    p.add_argument("--claude", default="claude",
                   help="the installed client to ask for its version (default: claude on PATH)")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        code, lines = measure(claude=args.claude, **inject)
    except Refusal as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:  # a crash is a missing reading, never an answer
        print("NO VERDICT: pending_update.py failed (%s: %s)" % (type(e).__name__, e))
        return 3
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
