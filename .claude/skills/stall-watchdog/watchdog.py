#!/usr/bin/env python3
"""Stall watchdog - answers a blocking confirmation prompt nobody is there to answer.

An unattended agent session runs with no human at the terminal, so a confirmation
prompt that no permission setting can suppress blocks the tool call forever. The
session's background watchers keep running and keep accepting inbound messages, so
from the outside a hang is indistinguishable from being ignored, and it lasts until
someone thinks to look at the terminal.

Claude Code carries at least one such guard - `Dangerous rm operation on
possibly-empty variable path`, whose own text says it "requires explicit approval
and cannot be auto-allowed by permission rules" - and it was seen with
`--dangerously-skip-permissions` and `⏵⏵ bypass permissions on` in the status line.
⚠️ What TRIPS it is a variable path inside a LOOP BODY (`for t in ...; do rm -rf
"$D/$t"; done`); the same paths written out literally do not, and neither does a
variable path outside a loop - technical/watchdog.md section 5 has the measurements
and their dates. Nothing here depends on knowing - the subject is any blocking prompt,
of which that guard is one instance.

This process sits OUTSIDE that session, reads its terminal with
`tmux capture-pane`, and when it finds a prompt that has sat untouched past the
timeout it answers **no** and tells the agent what it did.

⚠️ IT ALWAYS ANSWERS NO, AND THAT IS THE WHOLE DESIGN. Auto-approving would
defeat a guard that exists for a reason, and would do it unsupervised, which is
the worst possible combination. Answering no preserves the guard exactly - the
dangerous command does not run - while converting the failure from *fatal and
silent* into *a refused tool call the agent can see and route around*. A refusal
the agent can read is recoverable; a hang is not.

⚠️ THE WATCHDOG DOES NOT THINK. It has no idea whether "no" was the right answer,
and it says so in the message it injects, because an agent that believes a
considered decision was made on its behalf will not revisit it.

Two conditions must BOTH hold before it acts:

  1. the pane matches a prompt signature, and
  2. the pane has not changed for `stall_secs`

Condition 2 alone is meaningless - a session idling at its input prompt is
unchanged for hours and that is the normal resting state. Condition 1 alone is
not enough either: it would answer a prompt a human is actively reading. Requiring
both is what keeps Escape away from legitimate long-running work.

Configuration is selected by the STALL_WATCHDOG_CONFIG environment variable, set
in exactly one place per deployment: the systemd unit. There is deliberately no
config.json shipped beside this file, so a launcher that forgot the variable dies
naming the file it could not find, instead of quietly arming against a template
whose tmux target is a literal placeholder.

THE LOOP RE-EXECUTES ITSELF WHEN THIS FILE CHANGES ON DISK. The unit runs this
file from the host fleet checkout, which moves only by `fleet upgrade`, and the
unit itself is root-owned. Re-executing on a changed mtime is what lets an upgrade
reach a running watchdog with no sudo and no unit edit. See maybe_reexec() for the
one rule that keeps it from looping.

Usage:
  python3 watchdog.py             # poll loop - arm under a Monitor or systemd
  python3 watchdog.py --probe     # print what it sees right now, take no action
  python3 watchdog.py --once      # single evaluation, no loop
  python3 watchdog.py doctor      # resolved config + tmux reachability
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time

CONFIG_FILE = os.environ.get(
    "STALL_WATCHDOG_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
)
_MISSING = object()


def _strip_comments(obj):
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


try:
    # ⚠️ encoding is EXPLICIT because this daemon runs under systemd, which sets no
    # locale at all. The config is full of non-ASCII by design - the chooser glyph,
    # the status-bar arrows, the warning marks - so a locale-default read is an
    # ascii read on any system where Python's C-locale coercion is off, and it dies
    # at import naming a byte offset rather than the problem. Measured: the suite
    # aborts with UnicodeDecodeError under LC_ALL=C PYTHONCOERCECLOCALE=0.
    with open(CONFIG_FILE, encoding="utf-8") as fh:
        _CFG = json.load(fh)
except FileNotFoundError:
    sys.exit(f"WATCHDOG-CONFIG missing config file: {CONFIG_FILE}")
except json.JSONDecodeError as e:
    sys.exit(f"WATCHDOG-CONFIG {CONFIG_FILE} is not valid JSON: {e}")


def cfg(path, default=_MISSING):
    cur = _CFG
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            if default is _MISSING:
                sys.exit(f"WATCHDOG-CONFIG {CONFIG_FILE}: missing required key '{path}'")
            return default
        cur = cur[part]
    return _strip_comments(cur)


TMUX_TMPDIR = cfg("tmux.tmpdir")
TMUX_TARGET = cfg("tmux.target")
STALL_SECS = float(cfg("stall.stall_secs", default=3600))
POLL_SECS = float(cfg("stall.poll_secs", default=30))
PROMPT_PATTERNS = [re.compile(p, re.M) for p in cfg("stall.prompt_patterns")]
IDLE_PATTERNS = [re.compile(p, re.M) for p in cfg("stall.idle_patterns")]
IDLE_TAIL_LINES = int(cfg("stall.idle_tail_lines", default=6))
KNOWN_PROMPTS = [
    {**k, "_re": re.compile(k["match"], re.M)}
    for k in cfg("stall.known_prompts", default=[])
    if isinstance(k, dict) and not str(k.get("name", "")).startswith("_")
]
DENY_KEY = cfg("action.deny_key", default="Escape")
NOTICE = cfg("action.notice")
STATE_DIR = os.path.expanduser(cfg("state.dir"))
STATE_PREFIX = cfg("state.prefix", default="stall-watchdog")
OWNER_CONFIG_DIR = cfg("owner.claude_config_dir", default=None)


def log(kind, msg):
    print(f"WATCHDOG-{kind} {msg}", file=sys.stderr, flush=True)


def emit(msg):
    """stdout - becomes a wake-up line if this runs under a Monitor."""
    print(f"WATCHDOG {msg}", flush=True)


# --------------------------------------------------------------------------
# Pure decision logic. No clock, no subprocess - this is what the tests drive.
# --------------------------------------------------------------------------

def looks_like_prompt(pane: str) -> bool:
    """True if the pane appears to be showing a blocking confirmation prompt.

    ⚠️ Conservative on purpose. A false positive sends Escape into whatever the
    session is really doing; a false negative merely leaves the stall for a human.
    Of the two, only the first can destroy work.

    ⚠️ THE EXCLUSION MATTERS MORE THAN THE PATTERNS, because the pane being read
    also displays the agent's own commands and output. An agent that prints, greps
    or edits text containing a chooser - this very file does - would otherwise be
    detected as prompting itself.

    The reliable discriminator is structural rather than textual: a modal dialog
    REPLACES the input box and status bar at the foot of the pane. While the agent
    is idle or working those are always present; while a dialog is up they are
    always gone. So a tail carrying the idle signature means "not a prompt",
    whatever text happens to be on screen further up.
    """
    tail = "\n".join(pane.splitlines()[-IDLE_TAIL_LINES:])
    if any(p.search(tail) for p in IDLE_PATTERNS):
        return False
    return any(p.search(pane) for p in PROMPT_PATTERNS)


def idle_exclusion_hits(pane: str, tail_lines: int = None) -> list:
    """Which idle patterns fire inside the tail window, i.e. is the exclusion ARMED.

    ⚠️ THIS EXISTS BECAUSE "not a prompt" HAS TWO CAUSES AND ONLY ONE OF THEM IS
    PROTECTION. `looks_like_prompt()` returns False when the structural exclusion
    fires (safe: the footer is on screen, so this cannot be a dialog) and equally
    when it simply found no prompt pattern (unprotected: nothing is stopping a
    chooser that the agent PRINTS from being read as a real one). Both look
    identical from outside, and the second is how a healthy session gets Escaped.

    Measured on this fleet, and the reason this function is here: the session's
    idle footer sat SEVEN lines from the bottom of the pane because an agent-list
    panel is rendered below it, one line outside a six-line window. `--probe`
    reported `prompt match False` and read as a clean bill of health while the
    exclusion the design leans on was inert on every watched session.

    So the tail window is a MEASURED per-deployment value, not a constant. Any UI
    that renders anything below the status bar moves it. Re-measure with `--probe`
    after a terminal-UI change; SKILL.md step 5 makes that a required check.
    """
    n = IDLE_TAIL_LINES if tail_lines is None else tail_lines
    tail = "\n".join(pane.splitlines()[-n:])
    return [p.pattern for p in IDLE_PATTERNS if p.search(tail)]


def match_known_prompt(pane: str):
    """Return the taught handler for this pane, or None to fall back to refusing.

    ⚠️ Taught answers are strictly narrower than the default. Refusing is safe because
    it is uninformed - it declines to act. CHOOSING is not: it commits the session to
    one branch, so an entry here must be certain, and its `match` must be specific
    enough that it cannot fire on a different prompt that merely looks similar.

    Order is significant: first match wins, so put specific entries before general ones.
    """
    for k in KNOWN_PROMPTS:
        if k["_re"].search(pane):
            return k
    return None


def answer_keys_and_notify(keys, notice: str) -> None:
    """Send a taught key sequence, then explain into the session.

    Same ordering rule as the refusal path: the answer must land before the text, or
    the explanation is typed INTO the prompt as if it were the answer.
    """
    for key in keys:
        _tmux("send-keys", "-t", TMUX_TARGET, key)
        time.sleep(0.4)
    time.sleep(2)
    _tmux("send-keys", "-t", TMUX_TARGET, "-l", "--", notice)
    time.sleep(1)
    _tmux("send-keys", "-t", TMUX_TARGET, "Enter")


# Status glyphs that ANIMATE in place. Neutralised before hashing.
#
# ⚠️ This set is why the watchdog works at all, and it was got wrong once. The
# original version stripped only the footer, on the assumption that the token
# counter and spinner were the sole moving parts. They are not: while a prompt is
# up the session shows "● Running 1 shell command…" and the leading ● blinks -
# the SAME line alternates between "● Running…" and "  Running…" roughly every
# other second. That alternation changed the digest on every poll, so `since`
# reset on every poll, the stall timer never accumulated, and the watchdog would
# have sat there forever without firing - while systemd showed it healthy and its
# own tests passed against a synthetic fixture that did not blink.
#
# A watchdog that cannot fire is worse than none, because it stops anyone looking.
_ANIM_GLYPHS = re.compile(r"[●○◐◑◒◓✻✽✢∗⎿⏵❯·⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")
_VOLATILE_LINE = re.compile(r"esc to interrupt|tokens|\b\d+s\b", re.I)


def pane_digest(pane: str) -> str:
    """Hash the pane's MEANINGFUL content, ignoring anything that animates.

    Three normalisations, each earned: drop lines carrying live counters, replace
    animating glyphs, and collapse whitespace so a line that merely shifts
    indentation as a glyph appears and disappears hashes identically.

    Biasing toward "unchanged" is the safe direction here: firing additionally
    requires a prompt signature, so a digest that is slightly too stable can only
    cause a genuine stall to be answered, never a working session to be
    interrupted.
    """
    out = []
    for ln in pane.splitlines():
        if _VOLATILE_LINE.search(ln):
            continue
        ln = " ".join(_ANIM_GLYPHS.sub(" ", ln).split())
        if ln:
            out.append(ln)
    return hashlib.sha256("\n".join(out).encode()).hexdigest()[:16]


def decide(state: dict, digest: str, is_prompt: bool, now: float,
           stall_secs: float) -> tuple[str, dict]:
    """Return (action, new_state). action is 'wait' or 'deny'.

    State carries the digest last seen and when it was first seen. A `fired`
    latch prevents acting twice on one stall: after answering, nothing more
    happens until the pane actually changes, or a single unanswered prompt would
    be escaped every poll forever.
    """
    prev_digest = state.get("digest")
    if digest != prev_digest:
        return "wait", {"digest": digest, "since": now, "fired": False}

    st = dict(state)
    if not is_prompt:
        return "wait", st                       # unchanged but not a prompt: idle, fine
    if st.get("fired"):
        return "wait", st                       # already answered this one
    if now - st.get("since", now) < stall_secs:
        return "wait", st                       # not stalled long enough yet

    st["fired"] = True
    return "deny", st


# --------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------

def _tmux(*args, check=True) -> str:
    """Run a tmux client command against the server named by tmux.tmpdir.

    ⚠️ $TMUX IS DROPPED, AND THAT LINE IS LOAD-BEARING. When tmux runs inside a
    tmux session it inherits $TMUX, which carries the socket path of the server
    it is running under - and $TMUX WINS OVER $TMUX_TMPDIR. So a hand-run
    (`doctor`, `--probe`) issued from any agent's own tmux session talks to THAT
    agent's server instead of the configured one. Measured: `TMUX_TMPDIR=<one
    agent's dir> tmux ls`, typed inside another agent's session, listed the
    session it was typed in.

    ⚠️ How that presents depends on a coincidence. Where the two servers' session
    NAMES differ it is a loud "can't find session" - annoying, and harmless.
    Where they collide, which is exactly what a fleet naming its sessions by a
    common pattern produces, the capture SUCCEEDS against the wrong pane and
    everything downstream is confidently wrong: `--probe` vouches for a session
    it never read, and a loop launched that way would Escape a bystander.

    Under systemd there is no $TMUX, so the daemon was never exposed; every
    hand-run is.

    An `env -u TMUX` in front of the command does the same thing from the
    outside, and the documentation still says so for raw `tmux` invocations
    that do not come through here. This makes it unnecessary for this script.
    """
    env = dict(os.environ, TMUX_TMPDIR=TMUX_TMPDIR)
    env.pop("TMUX", None)
    r = subprocess.run(("tmux",) + args, env=env, capture_output=True, text=True, timeout=20)
    if check and r.returncode != 0:
        raise RuntimeError(f"tmux {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def capture_pane() -> str:
    return _tmux("capture-pane", "-p", "-t", TMUX_TARGET)


def format_notice(notice: str, stalled_for: float) -> str:
    """Fill the duration into the notice.

    ⚠️ The duration is substituted rather than written into the config text,
    because a hardcoded "60 minutes" silently becomes a lie the moment
    stall_secs is tuned - and it is the one sentence whose entire job is telling
    the agent how long it was gone. A notice that misstates that sends it looking
    for an hour-long gap that never happened.
    """
    secs = int(stalled_for)
    if secs >= 5400:
        human = f"{secs / 3600:.1f} hours"
    elif secs >= 90:
        human = f"{round(secs / 60)} minutes"
    else:
        human = f"{secs} seconds"
    return notice.replace("{duration}", human)


def answer_no_and_notify(notice: str) -> None:
    """Answer the prompt with a refusal, then tell the session what happened.

    Order matters: the refusal has to land first. Injecting the explanation while
    the prompt is still up would feed the text INTO the prompt as if it were the
    answer.
    """
    _tmux("send-keys", "-t", TMUX_TARGET, DENY_KEY)
    time.sleep(2)
    _tmux("send-keys", "-t", TMUX_TARGET, "-l", "--", notice)
    time.sleep(1)
    _tmux("send-keys", "-t", TMUX_TARGET, "Enter")


def load_state() -> dict:
    path = os.path.join(STATE_DIR, f"{STATE_PREFIX}.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{STATE_PREFIX}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, path)


def assert_owner() -> None:
    """Only the owning agent's config dir may run this. Exit 0 so a Monitor ends."""
    if not OWNER_CONFIG_DIR:
        return
    want = os.path.expanduser(OWNER_CONFIG_DIR)
    have = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR", ""))
    if want != have:
        log("GUARD", f"not the owning config dir (want {want}, have {have or '<unset>'})")
        sys.exit(0)


def acquire_singleton_lock():
    os.makedirs(STATE_DIR, exist_ok=True)
    fh = open(os.path.join(STATE_DIR, f"{STATE_PREFIX}.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("GUARD", "another watchdog holds the lock")
        sys.exit(0)
    return fh


SELF = os.path.abspath(__file__)


def self_mtime(path: str = SELF):
    """The mtime of this file in nanoseconds, or None when it cannot be read right now
    (mid-checkout, the file is briefly absent: that is not a change, so no re-exec)."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def maybe_reexec(recorded, path: str = SELF, execv=os.execv) -> bool:
    """Replace this process with a fresh run of the file when it changed on disk.

    ⚠️ IT COMPARES WITH THE MTIME RECORDED AT START, NEVER WITH THE CLOCK. "Newer than
    when I started" is the tempting test, and a file dated in the future - a clock
    skew, a restored backup, a checkout from a machine ahead of this one - satisfies
    it on every cycle, so the watchdog would re-execute every poll forever and never
    keep a stall timer long enough to fire. Inequality with its own recorded value is
    true exactly once per change. watchdog.test.py pins both directions.

    The lock is released by the exec itself: Python opens files non-inheritable, so the
    flock's descriptor closes and the fresh process takes the lock again on start.
    The stall cursor is on disk (save_state), so nothing is lost across the exec.
    Returns False when nothing changed; on a change it does not return.

    ⚠️ AN exec THAT FAILS EXITS 75, WITH ITS REASON IN THE LOG. sys.executable can
    stop existing under a running process: a Homebrew upgrade removes the Cellar path
    the interpreter was started from. The exit hands the restart to the service
    manager (Restart=always, launchd's KeepAlive), which starts the watchdog again
    from its unit's own interpreter path. It must never return into the loop: that
    would run the OLD code forever, the one thing this re-exec exists to prevent.
    """
    current = self_mtime(path)
    if recorded is None or current is None or current == recorded:
        return False
    log("INFO", f"{path} changed on disk - re-executing")
    try:
        execv(sys.executable, [sys.executable, *sys.argv])
    except OSError as e:
        log("ERROR", f"re-exec of {sys.executable} failed ({e}); exiting 75 so the service "
                     f"manager starts the watchdog again from its unit's interpreter")
        sys.exit(75)
    return True


def evaluate_once(state: dict, now: float) -> dict:
    pane = capture_pane()
    digest = pane_digest(pane)
    is_prompt = looks_like_prompt(pane)
    action, state = decide(state, digest, is_prompt, now, STALL_SECS)
    if action == "deny":
        stalled_for = int(now - state.get("since", now))
        known = match_known_prompt(pane)
        verb = f"answering '{known['name']}'" if known else "answering no"
        # Log the pane BEFORE acting: if the signature was wrong, this transcript is
        # the only evidence of what it actually matched.
        log("STALL", f"prompt unchanged {stalled_for}s - {verb}. Pane follows:")
        for ln in pane.splitlines()[-25:]:
            log("PANE", f"| {ln}")
        elapsed = now - state.get("since", now)
        if known:
            answer_keys_and_notify(known["keys"], format_notice(known["notice"], elapsed))
            emit(f"stall-answered after {stalled_for}s - taught prompt "
                 f"'{known['name']}' via {known['keys']}, session notified")
        else:
            answer_no_and_notify(format_notice(NOTICE, elapsed))
            emit(f"stall-denied after {stalled_for}s - answered NO and notified the session")
    return state


def main() -> None:
    argv = sys.argv[1:]
    if "doctor" in argv:
        print(f"config          {CONFIG_FILE}")
        print(f"tmux target     {TMUX_TARGET}  (TMUX_TMPDIR={TMUX_TMPDIR})")
        print(f"stall_secs      {STALL_SECS:.0f}  poll_secs {POLL_SECS:.0f}")
        print(f"deny key        {DENY_KEY}")
        print(f"state           {os.path.join(STATE_DIR, STATE_PREFIX + '.json')}")
        print(f"patterns        {[p.pattern for p in PROMPT_PATTERNS]}")
        try:
            pane = capture_pane()
            print(f"tmux            reachable, {len(pane.splitlines())} lines captured")
            print(f"prompt now?     {looks_like_prompt(pane)}")
            hits = idle_exclusion_hits(pane)
            print(f"idle exclusion  {'ARMED' if hits else 'INERT'} "
                  f"(last {IDLE_TAIL_LINES} lines) {hits}")
        except Exception as e:
            print(f"tmux            UNREACHABLE: {e}")
            sys.exit(1)
        return

    if "--probe" in argv:
        pane = capture_pane()
        print(f"--- pane ({len(pane.splitlines())} lines) ---")
        print(pane)
        print("--- verdict ---")
        print(f"digest        {pane_digest(pane)}")
        print(f"prompt match  {looks_like_prompt(pane)}")
        for p in PROMPT_PATTERNS:
            print(f"  {'HIT ' if p.search(pane) else 'miss'} {p.pattern}")
        hits = idle_exclusion_hits(pane)
        print(f"idle window   last {IDLE_TAIL_LINES} of {len(pane.splitlines())} lines")
        print(f"exclusion     {'ARMED' if hits else 'INERT'}  {hits}")
        if not hits:
            anywhere = [p.pattern for p in IDLE_PATTERNS if p.search(pane)]
            if anywhere:
                print("  ⚠️ the idle signature IS on screen but OUTSIDE the tail window "
                      f"({anywhere}). Raise stall.idle_tail_lines until it is inside, or "
                      "this session is protected by the prompt patterns alone - and a "
                      "chooser it merely PRINTS will be Escaped.")
            else:
                print("  ⚠️ no idle signature anywhere in the pane. Either a dialog is up "
                      "now, or stall.idle_patterns do not match this terminal UI.")
        return

    assert_owner()
    once = "--once" in argv
    started_mtime = self_mtime()
    if not once:
        _lock = acquire_singleton_lock()  # noqa: F841 - held for process lifetime
    log("INFO", f"watchdog up - target={TMUX_TARGET} stall={STALL_SECS:.0f}s poll={POLL_SECS:.0f}s")

    state = load_state()
    while True:
        try:
            state = evaluate_once(state, time.time())
            save_state(state)
        except Exception as e:  # a transient tmux failure must not kill the watchdog
            log("ERROR", f"{type(e).__name__}: {e}")
        if once:
            return
        time.sleep(POLL_SECS)
        maybe_reexec(started_mtime)


if __name__ == "__main__":
    main()
