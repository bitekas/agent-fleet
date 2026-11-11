#!/usr/bin/env bash
# tmux_triage.sh - the scripted generic parts of reviving a fleet agent: capture a
# tmux pane and classify it, extract a wrapped sign-in URL in full, read the agent's
# bootstrap prompt from its service unit, and answer WHICH account the session is
# signed in as and WHICH pool account it goes to next. The SIGN-IN itself
# is not here: it is a browser the reviving agent drives interactively
# (signin_driver/ beside this file, SKILL.md step 6), with a human in a real browser
# as the fallback.
#
# Hardcodes nothing: it takes the AGENT NAME as an argument and resolves that
# agent's tmux session, service unit and Claude config dir from config.json's
# templates (with <agent> substituted), and the account pool from its `accounts`
# block. The Claude Code UI wording it matches is the
# same for every install, so it lives here as mechanism.
#
#   tmux_triage.sh <agent>                    capture the LIVE pane and classify it
#   tmux_triage.sh <agent> --pane-file F      classify a pane captured to F (offline)
#   tmux_triage.sh <agent> --unit-file F      ... and resolve the agent's config dir
#                                             from unit file F instead of the live unit
#   tmux_triage.sh <agent> --bootstrap-prompt print the bootstrap prompt from the
#                                             live service unit
#   tmux_triage.sh <agent> --bootstrap-prompt --unit-file F   ... from unit file F (offline)
#   tmux_triage.sh <agent> --current-account  print the email of the account this
#                                             agent's session last signed in as
#   tmux_triage.sh <agent> --current-account --claude-json F  ... from F (offline)
#   tmux_triage.sh <agent> --accounts         list every pool account with its role
#                                             for this agent: current, leased-by-<x>,
#                                             next (the pool picker's pick) or free
#   tmux_triage.sh <agent> --accounts [--claude-json F] [--pool-file F]
#                  [--lease-file F] [--ledger F] [--now EPOCH]          (offline)
#   tmux_triage.sh <agent> --facts            print where everything of this agent
#                                             is, as one JSON object: its unit and the
#                                             service manager that runs it (unit_manager
#                                             systemd | launchd, unit_scope user |
#                                             system | file), its config
#                                             dir, tmux socket dir and target, and its
#                                             AUTH MODE - login, token or api-key -
#                                             with the auth file and the account it
#                                             names (`--unit-file F` offline)
#   tmux_triage.sh <agent> --config C         use config C (else $AGENT_REVIVE_CONFIG,
#                                             else the install's config.json, which
#                                             `fleet where agent-revive config.json`
#                                             resolves)
#
# The fleet command is this fleet tree's own bin/fleet, so a canary tree resolves
# with its own code; $FLEET_BIN overrides it (the tests' fake). The pool picker is
# the sibling skill's script, agent-health/pool_pick.py, reached through the fleet
# root this file resolves to with every symlink followed: invoked through an agent's
# skill link, the unresolved path names the link directory, whose parent holds only
# the links the install chose, not the fleet tree.
#
# THE AGENT'S UNIT IS READ FROM THE USER MANAGER FIRST, THEN THE SYSTEM MANAGER.
# The fleet's agent unit template is a user unit (`systemctl --user`), and the same
# file is a system unit after two edits, so an install can run either - or both,
# during a move from one to the other. Reading only one manager reads every agent
# the other runs as "no unit": its config dir falls back to convention, its auth
# mode to `login`, and its tmux socket to the config template. The manager that
# answered is reported (`unit_scope` in --facts), and it is the one a token
# agent's switch restarts through (token_switch.py). `systemctl --user` reaches the
# user's manager through XDG_RUNTIME_DIR, which a shell with no login session
# lacks, so it defaults to /run/user/<uid>. $FLEET_SYSTEMCTL replaces `systemctl`
# (the seam the offline tests inject a fake manager through).
#
# ON MACOS THE UNIT IS THE AGENT'S LAUNCHD JOB, read from its plist: the user's
# ~/Library/LaunchAgents/<label>.plist first, then /Library/LaunchDaemons/<label>.plist
# (unit_scope user | system), where <label> is fleet.systemd_unit with <agent>
# substituted (`<launchd_prefix>.session.<agent>` on a macOS install; the key keeps
# its name). templates/claude-agent.plist.example is the job's shape: the plist's
# EnvironmentVariables are read as the unit's Environment= lines, the session
# supervisor's `--env-file` argument as its EnvironmentFile=, and its `--boot`
# argument is the bootstrap prompt. `--unit-file F` takes a plist as well as a unit
# file (told apart by content). The service manager is chosen as fleetlib.services
# chooses it: $FLEET_SERVICE_BACKEND (systemd | launchd; the tests' seam), else
# launchd on macOS and systemd everywhere else. The plist is parsed by python3's
# plistlib, so the same reading runs on both systems. $FLEET_LAUNCHD_SYSTEM_DIR
# replaces /Library/LaunchDaemons (fleetlib.services' seam; HOME moves the user's).
#
# A PROTECTED MAC AGENT IS TOKEN-ONLY. With an administrator, a macOS agent's
# session is a LaunchDaemon (unit_scope system), which has no window server and no
# login Keychain: a browser sign-in cannot reach it, so it runs on a token or an API
# key, and its account switch is token_switch.py. A LaunchDaemon unit whose
# FLEET_AGENT_AUTH is login (or unset) is therefore auth `unknown`, its problem
# naming why: neither /login nor the sign-in driver is ever offered for it.
#
# PORTABLE: bash 3.2 and BSD grep/sed (macOS) as well as bash 5 and GNU. No grep -P,
# no \s in a regex (BSD grep need not know it): [[:space:]].
#
# THE AUTH MODE (--facts `auth`, and `auth` in every triage object) is the unit's
# last `FLEET_AGENT_AUTH=` assignment - the line the fleet's agent unit template
# records it in, beside the `EnvironmentFile=` that carries the credential:
#   login    the line says login, or the unit has no such line (every unit written
#            before the line existed): the session signs in through the browser
#            (SKILL.md steps 3-9), and an account switch is in-session.
#   token    the session runs on CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`,
#            read from the unit's EnvironmentFile= (the auth file). It does not
#            sign in through the browser; an account switch installs another
#            account's token and restarts the session through its unit
#            (token_switch.py); a dead token is reported, never revived.
#   api-key  the session bills per token on ANTHROPIC_API_KEY from the auth file,
#            has no plan windows and is in no pool.
#   mismatch a token or api-key unit whose auth file does not exist.
#   unknown  the unit could not be read, its value is none of the three, or it
#            names several EnvironmentFile= and none is `claude-auth.env`. ⚠️ AN
#            UNREADABLE UNIT IS NEVER READ AS login: that default walks a token
#            agent into /login, which replaces its configured credential with a
#            pool account's sign-in.
# The account a token agent runs as is its auth file's `# fleet-account:` header
# line, which pool_pick.py --take --install-token writes and pool_pick.py
# --read-auth-file reads - the leading comment lines only, never the line carrying
# the credential. A file with no header (one written by hand) names no account.
#
# Triage prints one JSON object: { agent, state, signin_url, banner, note, pane,
# daemons, daemons_expected, daemons_running, followers, followers_expected,
# followers_down, logs_replaced, last_turn_error, auth }.
# `banner` carries the matched usage-limit line for `usage-cap` and the session's
# last-message login line for `login-expired`, and is empty for every other state.
# `daemons` maps each daemon configured in fleet.daemons to true (a process whose
# command line carries its pattern runs WITH this agent's CLAUDE_CONFIG_DIR in its
# environment), false (none does), or null (the reading could not be taken - no
# process table, or a candidate whose environment could not be read). It is a
# reading of the machine, not of the pane, so it is taken in EVERY state.
# `daemons_expected` is the configured count; `daemons_running` counts the trues,
# and is null when any entry is null - a count over an unread entry is a guess.
# `last_turn_error` is the last `API Error:` line in the live area of the pane
# (continuation lines joined), else null.
# The process table is read from $AGENT_REVIVE_PROC_ROOT (default /proc), which is
# the seam the offline test injects a fake table through. ON MACOS (the launchd
# backend, with no AGENT_REVIVE_PROC_ROOT) there is no /proc and no process's
# environment can be read, so the reading is `agent-daemons.py status <agent>
# --json` instead: each of THIS agent's daemon jobs (a launchd label is per agent,
# so the job is the per-agent fact the environment is on Linux), with its state and
# its running process's argv. A daemon is true when an active job's argv carries its
# pattern, null when an active job's argv cannot be read and none matched, else
# false; no answer from agent-daemons.py at all is null. $AGENT_REVIVE_DAEMONS_STATUS
# replaces the `python3 <fleet>/systemd/agent-daemons.py` command (the tests' seam).
# `followers_expected` is the list of daemon jobs `agent-daemons.py status <agent>
# --json` reports `configured` for this agent (the scheduler and each working
# transport's watcher it runs), null when that gave no answer. `followers` maps each
# to true (a process whose argv is `<python> [-u...] <...>/systemd/agent-daemons.py
# follow <agent> <job>` runs with this agent's CLAUDE_CONFIG_DIR), false, or null
# (no process table, or an unreadable environment); on the launchd route, which has
# neither, it is empty. `followers_down` lists the jobs read false, in every state.
# `logs_replaced` lists the configured jobs whose daemon writes to a replaced log
# (`log_replaced` in `agent-daemons.py status <agent> --json`: its stdout or stderr
# is a deleted or moved file, not the one at the log path), in every state and on
# both routes: the follower reads a file that never grows, so the session hears
# nothing from that job exactly as if its follower were down. [] when status gave
# no answer.
# state is one of:
#   healthy      a ready status bar - nothing to revive
#   stopped      a ready status bar, daemons configured or followers expected, and
#                NONE of them runs: the session is idle and polling nothing, so
#                nothing will ever wake it. NOT a sign-in case. Read the pane for
#                unsent input text, then a wake line, typed by whoever CONTEXT.md
#                authorises (SKILL.md step 2)
#   follower-down a ready status bar and at least one expected follower read false,
#                or a job in logs_replaced, while something else can still wake it:
#                the session is deaf to that job's daemon (its scheduler, or its chat
#                transport). Never healthy. For followers_down the same remedy as
#                stopped: a wake line on which it re-arms the follower of each job;
#                for logs_replaced a restart of that job's unit, which the fleet's
#                refresh job makes on its next run (SKILL.md step 2)
#   auth-method  the login-method menu is up -> SKILL.md step 3 (Enter on option 1;
#                NEVER option 2, the metered API path)
#   signin-url   a sign-in URL is printed and the session waits for a pasted code;
#                signin_url carries the FULL url (wrapped lines joined)
#   status-modal the /status block is open on the pane -> read the account off it,
#                then DISMISS IT with Escape (SKILL.md step 5)
#   login-expired the session's LAST word is a dead-login result (`<reason> · Please
#                run /login`, as a top-level message or a `⎿` result row), its input
#                box has the focus, and no turn is running: an otherwise ready prompt
#                behind which every turn fails at once. No sign-in URL is printed in
#                this state. The /login route at the ready prompt (SKILL.md step 3),
#                the SAME account by default (step 5), the automated sign-in first
#                (step 6)
#   token-invalid the same dead-login last word as login-expired, on an agent whose
#                auth mode is token or api-key: its token (or key) has expired or
#                been revoked. NOT a revival: /login cannot fix it, because the
#                session keeps the token its environment gave it over any sign-in
#                (Claude Code 2.1.317: "OAuth 401: keeping the user-supplied
#                CLAUDE_CODE_OAUTH_TOKEN instead of adopting the stored
#                credential"). Report it to the operator: a fresh token from
#                `claude setup-token` for the account the auth file names (SKILL.md
#                step 5, case 15)
#   usage-cap    a usage-limit banner and no sign of a running turn: the quota
#                window looks exhausted -> SKILL.md step 5, case 14. Every cap lands
#                on this one state, so the `banner` line is the discriminator: a
#                session limit whose reset is imminent continues by itself and is
#                waited out, while a weekly cap or a session cap hours out is an
#                expired login and takes the account switch. ⚠️ It is a trigger to
#                LOOK, not a licence to type: confirm the `banner` line is the
#                session's own live state before sending any keystroke
#   working      the session is taking a turn right now (an interrupt hint, a live
#                spinner, an agent-tree row with a running timer, or the agents
#                panel - open in MANAGE mode, or listed under the prompt - over a
#                row with a running timer) - nothing to revive, and
#                stronger evidence than `healthy`, which means only READY
#   survey-prompt a "how is Claude doing this session?" rating prompt is drawn over
#                the input. A harmless IDLE state, not a revival case: send 0 to
#                dismiss it and re-triage
#   theme-prompt / scroll-prompt  a first-run selector -> SKILL.md step 9
#   unreachable  no tmux session at all - the agent is DOWN, not merely logged out
#   unknown      none of the above, or a dead-login result with a dialog or panel
#                holding the keys (its note says so); the captured pane comes back in
#                the `pane` field
#
# ⚠️ EVERY OUTPUT OF A TRIAGE RUN IS JSON, ON STDOUT, INCLUDING THE UNKNOWN CASE.
# A pane printed raw to stderr when nothing matches hands a caller that merges the
# two streams - which is what a tool call does by default - a screen of terminal
# decoration where it expects an object, and it reads that as the script failing
# rather than as a state it has not seen. The pane is the useful half of an
# `unknown`, so it is not dropped: it comes back INSIDE the object, in `pane`, which
# is empty for every other state.
#
# ⚠️ $TMUX beats $TMUX_TMPDIR: a tmux command run from inside a session reads THAT
# session's server. This script drops $TMUX from the child env (env -u TMUX) so a
# live capture always hits the configured server. A bare tmux you type by hand does
# not - prefix it with `env -u TMUX`.
#
# ⚠️ --accounts PRINTS USERNAMES AND NEVER PASSWORDS, AND THAT IS THE WHOLE REASON
# IT EXISTS. Picking which account to switch to otherwise means an operator running
# `cat` on the pool file, which puts EVERY account's PASSWORD on a pane, into a
# scrollback, and into a transcript that outlives the revival. This command answers
# the same question with the secret half never leaving the file. Delete it and the
# `cat` comes back. tmux_triage.test.sh asserts that no password from a pool file
# ever reaches stdout or stderr - that assertion is what keeps this property true,
# so it is not decoration either.
#
# ⚠️ --current-account reads the Claude config dir's .claude.json, which holds NO
# secret: the account email and profile only (the OAuth token lives in a separate
# .credentials.json this script never opens). It works with the session BLOCKED -
# at a `Paste code here` prompt no `/status` can run - which is exactly when the
# question "which account is this?" has to be answered. Do not "simplify" it into
# sending `/status` keystrokes: keystrokes need a session that can accept input,
# and a revival is by definition a session that cannot.
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
FLEET_ROOT="$(cd "$HERE/../../.." && pwd)"

agent=""; pane_file=""; unit_file=""; claude_json=""
pool_file=""; lease_file=""; ledger_file=""; now_epoch=""
mode="triage"; config="${AGENT_REVIVE_CONFIG:-}"
# A flag whose value is missing must die as a USAGE error (2), not as bash's own
# `$2: unbound variable`, which exits 1 - the code this script uses for a real
# fault. Same reason set_mode refuses a second mode flag instead of last-wins:
# `--current-account --accounts` silently ran accounts and answered a question
# nobody asked.
need2() { [ $# -ge 2 ] || { echo "flag $1 needs a value" >&2; exit 2; }; }
set_mode() { [ "$mode" = triage ] || { echo "pick ONE mode: --$1 conflicts with the mode already given" >&2; exit 2; }; mode="$1"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --pane-file)        need2 "$@"; pane_file="$2"; shift 2 ;;
    --unit-file)        need2 "$@"; unit_file="$2"; shift 2 ;;
    --pool-file)        need2 "$@"; pool_file="$2"; shift 2 ;;
    --lease-file)       need2 "$@"; lease_file="$2"; shift 2 ;;
    --ledger)           need2 "$@"; ledger_file="$2"; shift 2 ;;
    --now)              need2 "$@"; now_epoch="$2"; shift 2 ;;
    --claude-json)      need2 "$@"; claude_json="$2"; shift 2 ;;
    --bootstrap-prompt) set_mode bootstrap; shift ;;
    --current-account)  set_mode current-account; shift ;;
    --accounts)         set_mode accounts; shift ;;
    --facts)            set_mode facts; shift ;;
    --config)           need2 "$@"; config="$2"; shift 2 ;;
    # Print the WHOLE header comment, derived rather than pinned to line numbers: a
    # hardcoded range silently truncates --help mid-sentence the moment the header
    # grows, and the reader who notices is the one already lost.
    -h|--help)          awk 'NR>1 && /^#/ {print; next} NR>1 {exit}' "$0"; exit 0 ;;
    -*)                 echo "unknown flag: $1" >&2; exit 2 ;;
    *)                  if [ -z "$agent" ]; then agent="$1"; shift; else echo "unexpected arg: $1" >&2; exit 2; fi ;;
  esac
done
[ -n "$agent" ] || { echo "usage: tmux_triage.sh <agent> [--pane-file F | --bootstrap-prompt [--unit-file F] | --current-account [--claude-json F] | --accounts [--claude-json F] [--pool-file F] [--lease-file F] [--ledger F] [--now EPOCH] | --facts [--unit-file F]] [--config C]" >&2; exit 2; }
# ⚠️ <agent> IS REFUSED UNLESS IT IS AN AGENT NAME, BEFORE ANY USE, by the pattern
# bin/fleet holds every agent name to (fleetlib's paths.AGENT_NAME,
# `[a-z0-9][a-z0-9_-]*`). The name is spliced into a sed program (`sub`, below),
# joined into the agent's home path and handed to tmux and the daemon status call:
# a `/` ends the sed expression early and runs the rest as sed commands - GNU sed's
# `e` among them, which runs a shell command, measured doing so on a plain pane-file
# triage - and a `..` walks out of the agents root. The characters are spelled out
# because a range such as `a-z` follows the locale's collation, not ASCII.
case "$agent" in
  [!abcdefghijklmnopqrstuvwxyz0123456789]*|*[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
    printf 'not an agent name: %q (lowercase letters, digits, _ and -, starting with a letter or digit)\n' "$agent" >&2
    exit 2 ;;
esac
if [ -z "$config" ]; then
  fleet_bin="${FLEET_BIN:-$FLEET_ROOT/bin/fleet}"
  config="$("$fleet_bin" where agent-revive config.json)" \
    || { echo "cannot resolve the install's config: '$fleet_bin where agent-revive config.json' failed (pass --config or set AGENT_REVIVE_CONFIG)" >&2; exit 2; }
fi
[ -f "$config" ] || { echo "no config at $config (copy config.example.json to config.json in the install context, per installation/INSTRUCTION.md)" >&2; exit 2; }

# <agent> is the agent's name; <uid> is the numeric id of the user running this,
# the user every agent runs as - the user unit's runtime directory is
# /run/user/<uid>, so a tmux socket template for user units carries it.
sub() { printf '%s' "$1" | sed -e "s/<agent>/$agent/g" -e "s/<uid>/$(id -u)/g"; }
untilde() { case "$1" in "~"/*) printf '%s' "$HOME/${1#\~/}" ;; *) printf '%s' "$1" ;; esac; }
systemctl_bin="${FLEET_SYSTEMCTL:-systemctl}"
user_runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
backend="${FLEET_SERVICE_BACKEND:-}"
if [ -z "$backend" ]; then
  if [ "$(uname -s)" = Darwin ]; then backend=launchd; else backend=systemd; fi
fi

# A plist (XML or binary) rather than a systemd unit file.
is_plist() { case "$(head -c 8 "$1" 2>/dev/null)" in "<?xml"*|bplist*) return 0 ;; esac; return 1; }
# A launchd job's plist as the unit lines the rest of this script reads: each
# EnvironmentVariables entry as Environment=KEY="VALUE", the session supervisor's
# --env-file argument as EnvironmentFile=. Non-zero when it does not parse.
plist_unit() {
  python3 -c '
import plistlib, sys
d = plistlib.load(open(sys.argv[1], "rb"))
print("# launchd job %s, from %s" % (d.get("Label", "?"), sys.argv[1]))
for k, v in (d.get("EnvironmentVariables") or {}).items():
    print("Environment=%s=\"%s\"" % (k, v))
a = [str(x) for x in (d.get("ProgramArguments") or [])]
if "--env-file" in a[:-1]:
    print("EnvironmentFile=" + a[a.index("--env-file") + 1])
' "$1" 2>/dev/null
}
# The value of one argument flag in a plist's ProgramArguments (the session
# supervisor's --boot), or nothing.
plist_arg() {
  python3 -c '
import plistlib, sys
a = [str(x) for x in (plistlib.load(open(sys.argv[1], "rb")).get("ProgramArguments") or [])]
if sys.argv[2] in a[:-1]:
    print(a[a.index(sys.argv[2]) + 1])
' "$1" "$2" 2>/dev/null
}

# Read the agent's service unit into UNIT_TEXT and the manager that answered into
# UNIT_SCOPE (user | system | file, empty when nothing answered), the reason into
# UNIT_ERR, and a launchd job's plist path into UNIT_PLIST. User manager first, then
# the system manager, then the unit files the two would load - see THE AGENT'S UNIT
# above (and ON MACOS for launchd). Returns non-zero when no route answered.
load_unit() {
  local unit text f
  UNIT_TEXT=""; UNIT_SCOPE=""; UNIT_ERR=""; UNIT_PLIST=""
  unit="$(sub "$(jq -r '.fleet.systemd_unit' "$config")")"
  if [ -n "$unit_file" ]; then
    [ -f "$unit_file" ] || { UNIT_ERR="no unit file at $unit_file"; return 1; }
    if is_plist "$unit_file"; then
      text="$(plist_unit "$unit_file")" || { UNIT_ERR="unit file $unit_file is a plist that does not parse"; return 1; }
      UNIT_TEXT="$text"; UNIT_PLIST="$unit_file"; UNIT_SCOPE="file"; return 0
    fi
    UNIT_TEXT="$(cat "$unit_file")"; UNIT_SCOPE="file"; return 0
  fi
  if [ "$backend" = launchd ]; then
    local sysdir="${FLEET_LAUNCHD_SYSTEM_DIR:-/Library/LaunchDaemons}"
    for f in "$HOME/Library/LaunchAgents/$unit.plist" "$sysdir/$unit.plist"; do
      [ -f "$f" ] || continue
      if text="$(plist_unit "$f")"; then
        UNIT_TEXT="$text"; UNIT_PLIST="$f"
        if [ "$f" = "$sysdir/$unit.plist" ]; then UNIT_SCOPE="system"; else UNIT_SCOPE="user"; fi
        return 0
      fi
    done
    UNIT_ERR="cannot read the agent's launchd job '$unit' (no readable plist at $HOME/Library/LaunchAgents/$unit.plist or $sysdir/$unit.plist)"
    return 1
  fi
  if text="$(XDG_RUNTIME_DIR="$user_runtime" "$systemctl_bin" --user cat "$unit" 2>/dev/null)" && [ -n "$text" ]; then
    UNIT_TEXT="$text"; UNIT_SCOPE="user"; return 0
  fi
  if text="$("$systemctl_bin" cat "$unit" 2>/dev/null)" && [ -n "$text" ]; then
    UNIT_TEXT="$text"; UNIT_SCOPE="system"; return 0
  fi
  local f
  for f in "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$unit" "/etc/systemd/system/$unit"; do
    if text="$(cat "$f" 2>/dev/null)" && [ -n "$text" ]; then
      UNIT_TEXT="$text"
      case "$f" in /etc/*) UNIT_SCOPE="system" ;; *) UNIT_SCOPE="user" ;; esac
      return 0
    fi
  done
  UNIT_ERR="cannot read service unit '$unit' (neither 'systemctl --user cat' nor 'systemctl cat' answered, and no unit file under ${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user or /etc/systemd/system)"
  return 1
}

# The unit onto stdout; non-zero (with the reason on stderr) when it cannot be read.
# ⚠️ IT MUST NEVER CALL exit: every caller reads it through a command substitution,
# and an `exit` inside one kills only the SUBSHELL - the script then carries on with
# an empty string and fails later, under a different message and a different exit
# code than the real fault. Callers decide what a failure means: --bootstrap-prompt
# cannot work without the unit and exits 2; --current-account only wants
# CLAUDE_CONFIG_DIR out of it and falls back to the fleet layout.
unit_text() {
  load_unit || { echo "$UNIT_ERR" >&2; return 1; }
  printf '%s\n' "$UNIT_TEXT"
}

# The LAST value systemd keeps for one variable of the unit's Environment= lines,
# or nothing. ⚠️ tail -1, NEVER head -1: systemd's rule is LAST assignment wins,
# and `systemctl cat` prints the unit followed by every drop-in - which is the
# normal way an Environment= is changed without editing the unit. head -1 returns
# the assignment systemd DISCARDED, and that is the worst shape of wrong here: the
# stale value is the one that still EXISTS, so a lookup with it succeeds and prints
# another account's email with exit 0 and a confident provenance line.
# ⚠️ The match is not anchored to the start of the value either: `Environment=`
# legally carries several assignments on one line and legally quotes them, and an
# anchored regex fell through to the convention path with no message at all.
unit_env() {
  grep -E '^[[:space:]]*Environment=' <<<"$1" \
    | grep -oE "$2=(\"[^\"]*\"|[^[:space:]]*)" \
    | tail -1 | sed -E "s/^$2=//; s/^\"//; s/\"\$//"
}

# The tmux socket dir: the unit's own TMUX_TMPDIR, with %t expanded for the manager
# that runs it (/run/user/<uid> for the user's, /run for the system's) - the value
# the session was created with - else the config template. Same precedence as the
# config dir below, for the same reason: the unit is truth, the template convention.
resolve_tmpdir() {
  local text="${UNIT_TEXT:-}" dir
  if [ -z "$text" ] && load_unit 2>/dev/null; then text="$UNIT_TEXT"; fi
  dir="$(unit_env "$text" TMUX_TMPDIR)"
  if [ -n "$dir" ]; then
    case "$UNIT_SCOPE" in system) dir="${dir//%t//run}" ;; *) dir="${dir//%t/$user_runtime}" ;; esac
    # Any other specifier (%i, %u, %h ...) is systemd's to expand, not this script's:
    # a path still carrying one names no directory, so the template answers instead.
    case "$dir" in *%*) ;; *) printf '%s' "$dir"; return 0 ;; esac
  fi
  printf '%s' "$(sub "$(jq -r '.fleet.tmux.tmpdir' "$config")")"
}

# The auth mode, into AUTH / AUTH_FILE / AUTH_ACCOUNT / AUTH_PROBLEM (see THE AUTH
# MODE above), and UNIT_READ (yes | no). Reads the unit through load_unit, never in
# a subshell.
auth_facts() {
  local mode files n f hdr
  AUTH=unknown; AUTH_FILE=""; AUTH_ACCOUNT=""; AUTH_PROBLEM=""; UNIT_READ=no
  [ -n "${UNIT_SCOPE:-}" ] || load_unit 2>/dev/null || true
  if [ -z "${UNIT_TEXT:-}" ]; then
    AUTH_PROBLEM="the agent's unit could not be read (${UNIT_ERR:-no unit}), so how it signs in (FLEET_AGENT_AUTH) is not known"
    return 0
  fi
  UNIT_READ=yes
  mode="$(unit_env "$UNIT_TEXT" FLEET_AGENT_AUTH)"
  if [ "$backend" = launchd ] && [ "$UNIT_SCOPE" = system ] && [ "${mode:-login}" = login ]; then
    AUTH_PROBLEM="a protected macOS agent's session is a LaunchDaemon, which has no window server and no login Keychain, so it signs in only with a token or an API key; this one's unit sets FLEET_AGENT_AUTH='${mode:-}' - give it a token (SKILL.md step 5, a token agent) and set FLEET_AGENT_AUTH=token; neither /login nor the sign-in driver can reach it"
    return 0
  fi
  case "${mode:-login}" in
    login) AUTH=login; return 0 ;;
    token|api-key) AUTH="$mode" ;;
    *) AUTH_PROBLEM="the unit sets FLEET_AGENT_AUTH='$mode', which is none of login, token, api-key"; return 0 ;;
  esac
  files="$(grep -E '^[[:space:]]*EnvironmentFile=' <<<"$UNIT_TEXT" \
           | sed -E 's/^[[:space:]]*EnvironmentFile=-?//; s/^"//; s/"[[:space:]]*$//; s/[[:space:]]+$//')"
  n="$(grep -c . <<<"$files")"
  if [ "$n" = 1 ]; then
    AUTH_FILE="$(untilde "$files")"
  else
    while IFS= read -r f; do
      case "$f" in */claude-auth.env) AUTH_FILE="$(untilde "$f")" ;; esac
    done <<<"$files"
  fi
  if [ -z "$AUTH_FILE" ]; then
    AUTH=unknown; AUTH_PROBLEM="a $mode unit must name its credential file in EnvironmentFile=; this one names $n and none is claude-auth.env"
    return 0
  fi
  if [ ! -f "$AUTH_FILE" ]; then
    AUTH=mismatch; AUTH_PROBLEM="the $mode unit loads $AUTH_FILE, which does not exist"
    return 0
  fi
  hdr="$(python3 "$FLEET_ROOT/.claude/skills/agent-health/pool_pick.py" --read-auth-file "$AUTH_FILE" 2>/dev/null)" || true
  AUTH_ACCOUNT="$(jq -r '.account // empty' <<<"$hdr" 2>/dev/null)"
}

# --- bootstrap-prompt mode: read the first quoted send-keys arg from ExecStartPost ---
# The service unit's ExecStartPost injects the agent's first-turn prompt via a
# `tmux send-keys -t <target> "<PROMPT>"`, followed by a separate send-keys of the
# bare `Enter`. Reviving in-session does not re-run ExecStartPost, so this reads the
# prompt back out of the unit rather than hardcoding any agent's wording here.
if [ "$mode" = "bootstrap" ]; then
  unit="$(sub "$(jq -r '.fleet.systemd_unit' "$config")")"
  load_unit || { echo "$UNIT_ERR" >&2; exit 2; }
  # A launchd job: the session supervisor's --boot argument IS the prompt.
  if [ -n "$UNIT_PLIST" ]; then
    prompt="$(plist_arg "$UNIT_PLIST" --boot)"
    [ -n "$prompt" ] || { echo "launchd job '$unit' ($UNIT_PLIST) has no --boot argument - nothing to inject" >&2; exit 1; }
    printf '%s\n' "$prompt"
    exit 0
  fi
  exec_line="$(grep -E '^[[:space:]]*ExecStartPost=' <<<"$UNIT_TEXT" | head -1)"
  [ -n "$exec_line" ] || { echo "unit '$unit' has no ExecStartPost line - nothing to inject" >&2; exit 1; }
  # The prompt is the FIRST double-quoted argument to a `send-keys` (the bare Enter
  # that follows is unquoted, so it never matches): the text from the first quote
  # after the first `send-keys` to the next quote. Assumes the prompt carries no
  # unescaped double quote, which the fleet's bootstrap prompts do not. Parameter
  # expansion, not grep -P (GNU only).
  prompt=""
  rest="${exec_line#*send-keys}"
  if [ "$rest" != "$exec_line" ]; then
    case "$rest" in *'"'*) rest="${rest#*\"}"; prompt="${rest%%\"*}" ;; esac
  fi
  [ -n "$prompt" ] || { echo "found ExecStartPost but no quoted send-keys prompt in it (unit '$unit')" >&2; exit 1; }
  printf '%s\n' "$prompt"
  exit 0
fi

# --- which account is this session signed in as? -------------------------------
# Claude Code writes the account it last authenticated as into .claude.json in its
# config dir, under .oauthAccount.emailAddress. That file is readable with the
# session blocked, so this answers the question when `/status` cannot be run.
#
# The config dir is resolved in this order, most authoritative first:
#   1. the service unit's `Environment=CLAUDE_CONFIG_DIR=...` - the value the
#      session was actually started with, so it is truth rather than convention;
#   2. <fleet.agents_home>/<agent>/.claude - the fleet convention, used when the
#      unit is unreadable (a session started by hand, a host without systemd).
# Nothing new is added to config.json for this: route 1 is already-recorded machine
# state and route 2 is already-configured fleet layout.
resolve_claude_json() {
  if [ -n "$claude_json" ]; then printf '%s' "$claude_json"; return 0; fi
  printf '%s' "$(resolve_config_dir)/.claude.json"
}
# The agent's Claude config dir, by the two routes above. Shared by
# --current-account and the daemon-liveness reading: one resolution, so the two can
# never disagree about which directory is this agent's.
resolve_config_dir() {
  local text dir ah
  # 2>/dev/null: an unreadable unit is not a fault HERE, only a missing hint.
  text="$(unit_text 2>/dev/null)" || text=""
  if [ -n "$text" ]; then
    # The LAST assignment, with the reasons unit_env carries.
    dir="$(unit_env "$text" CLAUDE_CONFIG_DIR)"
    if [ -n "$dir" ]; then printf '%s' "$(untilde "$dir")"; return 0; fi
  fi
  # ⚠️ The convention path ends in the CONFIG DIR, `.claude`, and then the file
  # inside it - dropping that segment names a path that never exists, so the
  # fallback silently degrades into "no recorded login" and turns a knowable answer
  # into a guess. It is masked wherever route 1 fires, i.e. everywhere except the
  # hosts this fallback exists for.
  ah="$(untilde "$(jq -r '.fleet.agents_home' "$config")")"
  printf '%s' "$ah/$agent/.claude"
  return 0
}

# Prints the email on stdout and the provenance on stderr; returns 1, naming the
# route that failed, when it cannot answer. NEVER returns 0 with an empty or guessed
# answer: an unknown current account must read as UNKNOWN, because "guess and
# switch" signs an agent in as the wrong principal (SKILL.md step 5, case 4).
# ⚠️ A TOKEN AGENT'S ACCOUNT IS ITS AUTH FILE'S `# fleet-account:` LINE, NOT
# .claude.json. A session on an environment token records no sign-in there, and its
# /status shows `Auth token: CLAUDE_CODE_OAUTH_TOKEN` with no Email: line (measured
# 2026-11-06 on 2.1.317): the token it was STARTED with is the only account it has,
# and the header of the file that token came from names it.
current_account() {
  local f email
  # An UNREADABLE unit keeps the .claude.json route below (a session started by
  # hand, a host without systemd): that file names no account for a token agent, so
  # the route cannot mistake one for a login agent's account.
  if [ -z "$claude_json" ]; then
    auth_facts
    case "$AUTH:$UNIT_READ" in
      token:*)
        if [ -n "$AUTH_ACCOUNT" ]; then
          echo "source: $AUTH_FILE ('# fleet-account:' header - the account whose token the session was started with)" >&2
          printf '%s\n' "$AUTH_ACCOUNT"; return 0
        fi
        echo "the auth file $AUTH_FILE names no account (no '# fleet-account:' header: it was not installed by pool_pick.py --take --install-token) - cannot say which account this token agent runs as" >&2
        return 1 ;;
      api-key:*)
        echo "this agent runs on an API key ($AUTH_FILE): it is billed per token and is in no account pool" >&2
        return 1 ;;
      mismatch:*|unknown:yes)
        echo "auth mode $AUTH: $AUTH_PROBLEM - resolve it before reading an account" >&2
        return 1 ;;
    esac
  fi
  f="$(resolve_claude_json)"
  if [ ! -f "$f" ]; then
    echo "no Claude state file at $f - cannot say which account this agent is signed in as" >&2
    return 1
  fi
  email="$(jq -r '.oauthAccount.emailAddress // empty' "$f" 2>/dev/null)"
  if [ -z "$email" ]; then
    echo "$f has no .oauthAccount.emailAddress - this agent has no recorded successful login (never signed in, or a different config dir is in use)" >&2
    return 1
  fi
  echo "source: $f (.oauthAccount.emailAddress - the LAST SUCCESSFUL login, which is the account that expired)" >&2
  printf '%s\n' "$email"
  return 0
}

if [ "$mode" = "current-account" ]; then
  current_account || exit 1
  exit 0
fi

# --- facts mode: where everything of this agent is ------------------------------
# One JSON object, read-only, no keystroke: the unit and the manager that runs it,
# the config dir, the tmux socket dir and target a hand-run tmux call needs, and the
# auth mode with its file and account. Exit 0 when the auth mode is one a switch can
# act on (login, token, api-key); exit 1 for mismatch or unknown, with the problem
# in `auth_problem` - no switch and no sign-in until a person fixes it.
if [ "$mode" = "facts" ]; then
  load_unit 2>/dev/null || true
  auth_facts
  jq -n --arg a "$agent" --arg u "$(sub "$(jq -r '.fleet.systemd_unit' "$config")")" \
        --arg b "$backend" --arg s "$UNIT_SCOPE" --arg c "$(resolve_config_dir)" --arg d "$(resolve_tmpdir)" \
        --arg t "$(sub "$(jq -r '.fleet.tmux.target' "$config")")" --arg m "$AUTH" \
        --arg f "$AUTH_FILE" --arg ac "$AUTH_ACCOUNT" --arg p "$AUTH_PROBLEM" \
    '{agent:$a, unit:$u, unit_manager:$b, unit_scope:(if $s == "" then null else $s end), config_dir:$c,
      tmux_tmpdir:$d, tmux_target:$t, auth:$m,
      auth_file:(if $f == "" then null else $f end),
      auth_account:(if $ac == "" then null else $ac end),
      auth_problem:(if $p == "" then null else $p end)}'
  case "$AUTH" in login|token|api-key) exit 0 ;; *) exit 1 ;; esac
fi

# --- accounts mode: the pool, and which account this agent goes to next -------
# The Claude login belongs to no agent: every account is one POOL
# (accounts.pool_file), and which agent holds which account is the LEASE file
# (accounts.lease_file). The pick is not computed here. It is the pool picker's
# (agent-health's pool_pick.py, beside this skill in the fleet tree), which reads the pool, the leases
# and the usage ledger, reconciles the leases against this agent's real login, and
# prints usernames and reasons only. This mode renders that answer as a table, one
# row per pool account, in pool order:
#
#   <username> TAB <role> TAB <why>
#
# role is `current` (this agent's session is on it), `leased-by-<agent>`, `next`
# (the picker's pick) or `free`; the third column is the picker's note, which says
# why a free account was not picked (excluded, over the weekly line, ...).
#
# ⚠️ THIS SCRIPT NEVER OPENS THE POOL FILE. Only the picker reads it, in-process,
# and it prints no password on any path - so `--accounts` has no secret to handle,
# and tmux_triage.test.sh still asserts that no fixture password reaches either
# stream, because a future "debug" field dump in the picker would reach both.
#
# ⚠️ THE TABLE AND THE VERDICT MUST AGREE: exit 0 means a `next` row exists and
# nothing disagrees; every other state - current account unknown, the leases
# disagreeing with the session, the pool exhausted, a pool or lease file that cannot
# be read - marks NO row `next` and exits 1, with the reason on stderr. A table that
# names a switch target while stderr says none exists is read as the half the reader
# already believed.
if [ "$mode" = "accounts" ]; then
  picker="$FLEET_ROOT/.claude/skills/agent-health/pool_pick.py"
  [ -f "$picker" ] || { echo "no pool picker at $picker (the agent-health skill must sit beside agent-revive in the fleet tree)" >&2; exit 2; }

  # The agent's auth mode decides which accounts it can use at all: a token agent
  # only those with a token file, a login agent only those with a password. An
  # api-key agent is in no pool, and a mismatch or an unknown mode is a STOP - an
  # unreadable unit included, because a pick made for the wrong mode names an
  # account the agent cannot be moved onto. `--claude-json` (offline) is a login
  # agent's reading by construction.
  auth="login"
  if [ -z "$claude_json" ]; then
    auth_facts; auth="$AUTH"
    case "$auth" in
      api-key) echo "this agent runs on an API key: it is in no account pool and has no account to switch (SKILL.md step 5, case 15)" >&2; exit 1 ;;
      mismatch|unknown) echo "STOP - auth mode $auth: $AUTH_PROBLEM (SKILL.md step 5, case 15)" >&2; exit 1 ;;
    esac
  fi
  cur="$(current_account 2>/dev/null)" || cur=""
  pargs=(--config "$config" --agent "$agent" --auth "$auth")
  [ -n "$cur" ]         && pargs+=(--current "$cur")
  [ -n "$pool_file" ]   && pargs+=(--pool "$pool_file")
  [ -n "$lease_file" ]  && pargs+=(--leases "$lease_file")
  [ -n "$ledger_file" ] && pargs+=(--ledger "$ledger_file")
  [ -n "$now_epoch" ]   && pargs+=(--now "$now_epoch")

  # stderr to a file, never merged: stdout is the picker's ONE JSON object.
  perr="$(mktemp)"
  pick_json="$(python3 "$picker" "${pargs[@]}" 2>"$perr")"; prc=$?
  pick_err="$(cat "$perr")"; rm -f "$perr"
  if [ "$prc" -ge 2 ] || ! jq -e 'has("accounts")' <<<"$pick_json" >/dev/null 2>&1; then
    [ -n "$pick_err" ] && printf '%s\n' "$pick_err" >&2
    echo "STOP - the pool picker could not read its inputs (exit $prc), so no account is offered; that is an escalation, not a guess (SKILL.md step 5, cases 8, 9 and 10)" >&2
    exit 1
  fi

  rc=0; msgs=()
  pick="$(jq -r '.pick // empty' <<<"$pick_json")"
  if [ -z "$cur" ]; then
    msgs+=("current account UNKNOWN - no 'next' is marked, because the leases cannot be reconciled against a login nobody can read. Resolve it first (SKILL.md step 5, case 3b); do not guess.")
    pick=""; rc=1
  elif [ -z "$pick" ]; then
    rc=1
  fi
  while IFS= read -r m; do [ -n "$m" ] && msgs+=("$m"); done < <(jq -r '.problems[]' <<<"$pick_json")
  msgs+=("pick: $(jq -r '.reason' <<<"$pick_json")")

  jq -r --arg cur "$cur" --arg pick "$pick" '
    .accounts[]
    | [ .username,
        (if $cur != "" and .username == $cur then "current"
         elif $pick != "" and .username == $pick then
           (if .leased_by != null then "next-shared-with-" + .leased_by else "next" end)
         elif .leased_by != null then "leased-by-" + .leased_by
         else "free" end),
        (.note // "") ]
    | join("\t")' <<<"$pick_json"

  for m in ${msgs+"${msgs[@]}"}; do echo "$m" >&2; done
  exit "$rc"
fi

# --- triage mode ---
target="$(sub "$(jq -r '.fleet.tmux.target' "$config")")"
# The auth mode travels in every triage object: it decides what a dead login MEANS
# (login-expired for a login agent, token-invalid for a token or api-key agent) and
# which remedy a caller may take.
auth_facts

# ── daemon liveness: is anything running BEHIND the pane? ──────────────────────
# ⚠️ AN IDLE PROMPT WITH NOTHING RUNNING BEHIND IT IS INDISTINGUISHABLE FROM A
# HEALTHY QUIET HOUR BY PANE ALONE. A fleet agent stays responsive because daemons it
# armed (an inbound-message watcher, a scheduler) wake it; when its last turn ends on
# an error after those watches expired, the pane shows a ready prompt and nothing
# will ever wake it again, and every hourly sweep reads `healthy` (SKILL.md,
# Measured). So this reads the PROCESS TABLE, not the pane: for each daemon in
# fleet.daemons, does a process run whose command line carries the daemon's pattern
# (a literal substring of one argument) AND whose environment carries THIS agent's
# CLAUDE_CONFIG_DIR? The environment is what makes the reading per-agent: every agent
# on a fleet runs the same watcher script, so a command-line match alone answers
# "does ANY agent run it", which is green for a stopped agent whenever a peer is up.
#
# THREE outcomes per daemon, never two: true / false / null. null means the reading
# was not taken - no process table at the root, or a candidate whose environment
# EXISTS but cannot be read (another user's process), with no candidate that matched.
# A null never becomes `stopped`: a sweep that cannot read the table must not report
# every agent on the fleet as stopped, which is the comfortable verdict manufactured
# by a broken instrument.
# ⚠️ A candidate that EXITED between the scan and the environment read (its environ
# is gone) is skipped, NOT read as null: it is positively not running. Read as null,
# any transient process quoting the pattern - a peer's grep, a sweep command - voids
# the reading for every agent it lands on, and a stopped agent reads `healthy` again.
# ⚠️ The pattern goes to grep through -f <(...), never as an argument, so grep's own
# command line - which is in the glob it scans - cannot make grep a candidate.
# ⚠️ Residual, stated so nobody reads more into a `true` than it says: any process in
# this agent's environment whose command line merely MENTIONS the pattern counts -
# e.g. the shell wrapper a daemon runs under (dies with the daemon, so harmless), or a
# command the agent happens to be running that quotes the path. The latter is
# transient and errs toward `healthy`, the state this reading only ever refines.
proc_root="${AGENT_REVIVE_PROC_ROOT:-/proc}"
# The launchd route (see the header): taken when no proc root is injected and the
# backend is launchd. daemons_status is agent-daemons.py's JSON, read once.
daemon_route=proc
[ -z "${AGENT_REVIVE_PROC_ROOT:-}" ] && [ "$backend" = launchd ] && daemon_route=launchd
daemons_status=""

# Prints true | false | null for one pattern and one config dir.
daemon_reading() {
  if [ "$daemon_route" = launchd ]; then
    # Positive evidence first: an answer that is not agent-daemons.py's JSON is no
    # reading, never a set of stopped daemons.
    jq -e '.jobs | type == "object"' <<<"$daemons_status" >/dev/null 2>&1 || { echo null; return; }
    jq -r --arg p "$1" '[.jobs[] | select(.active == "active" and (.pid // 0) > 0)] as $up
      | if any($up[]; (.argv // []) | any(.[]; contains($p))) then "true"
        elif any($up[]; .argv == null) then "null" else "false" end' <<<"$daemons_status"
    return
  fi
  local pattern="$1" want="${2%/}" files f envs have unread=0
  # Positive evidence that the instrument sees a process table at all. Without it a
  # wrong root reads as "nothing runs anywhere" and every idle agent reads `stopped`.
  compgen -G "$proc_root/[0-9]*/cmdline" >/dev/null || { echo null; return; }
  # The grep exit code is NOT read: a process exiting mid-scan makes grep return 2
  # alongside real matches. The OUTPUT is the reading.
  files="$(grep -alF -f <(printf '%s\n' "$pattern") "$proc_root"/[0-9]*/cmdline 2>/dev/null)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "${f%/cmdline}/environ" ] || continue               # exited: not running
    if ! envs="$(tr '\0' '\n' < "${f%/cmdline}/environ" 2>/dev/null)"; then unread=1; continue; fi
    have="$(grep -m1 '^CLAUDE_CONFIG_DIR=' <<<"$envs")"
    have="${have#CLAUDE_CONFIG_DIR=}"
    if [ -n "$have" ] && [ "${have%/}" = "$want" ]; then echo true; return; fi
  done <<<"$files"
  if [ "$unread" = 1 ]; then echo null; else echo false; fi
}

# is_follower <cmdline file> <job>: the process is THIS agent's follower of <job>,
# read by argv POSITION: an interpreter (python, python3, python3.N), any of its
# single-letter flags (-u -B -I -E -s -S -O), a script path ending in
# systemd/agent-daemons.py, then `follow`, this agent and the job - the command the
# agent unit's boot message arms. ⚠️ NEVER A SUBSTRING: a process that merely QUOTES
# the follower command - self-compact's detached sender carries a wake line naming
# it, in this agent's environment, for minutes - would read as a follower that is
# not there.
is_follower() {
  local a k=1
  local -a av=()
  while IFS= read -r a; do av+=("$a"); done < <(tr '\0' '\n' < "$1" 2>/dev/null)
  [ "${#av[@]}" -ge 5 ] || return 1
  case "${av[0]##*/}" in python | python3 | python3.[0-9]*) ;; *) return 1 ;; esac
  while [ "$k" -lt "${#av[@]}" ]; do
    case "${av[$k]}" in -[uBIEsSO]*) k=$((k + 1)) ;; *) break ;; esac
  done
  [ $((k + 3)) -lt "${#av[@]}" ] || return 1
  case "${av[$k]}" in */systemd/agent-daemons.py | systemd/agent-daemons.py) ;; *) return 1 ;; esac
  [ "${av[$((k + 1))]}" = follow ] && [ "${av[$((k + 2))]}" = "$agent" ] && [ "${av[$((k + 3))]}" = "$2" ]
}

# Prints true | false | null: does a follower of <job> (is_follower) run with config
# dir <dir> in its environment? The same three outcomes and the same reasons as
# daemon_reading: null when no process table is seen or a follower's environment
# cannot be read and none matched; an exited candidate is skipped.
follower_reading() {
  local job="$1" want="${2%/}" files f envs have unread=0
  compgen -G "$proc_root/[0-9]*/cmdline" >/dev/null || { echo null; return; }
  # The substring only narrows the candidates; is_follower decides.
  files="$(grep -alF -f <(printf '%s\n' 'agent-daemons.py') "$proc_root"/[0-9]*/cmdline 2>/dev/null)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_follower "$f" "$job" || continue
    [ -e "${f%/cmdline}/environ" ] || continue               # exited: not running
    if ! envs="$(tr '\0' '\n' < "${f%/cmdline}/environ" 2>/dev/null)"; then unread=1; continue; fi
    have="$(grep -m1 '^CLAUDE_CONFIG_DIR=' <<<"$envs")"
    have="${have#CLAUDE_CONFIG_DIR=}"
    if [ -n "$have" ] && [ "${have%/}" = "$want" ]; then echo true; return; fi
  done <<<"$files"
  if [ "$unread" = 1 ]; then echo null; else echo false; fi
}

# fleet.daemons: a list of {name, pattern}. Only an OBJECT whose sole key is
# `_comment` is documentation and dropped; every other entry - a bare string included
# - must be well-formed or the run exits 2, because an entry silently dropped is a
# daemon silently not checked: the false `healthy` this reading exists to remove.
daemon_cfg="$(jq -c '(.fleet.daemons // []) | if type == "array" then . else error("not a list") end
                     | [.[] | select(if type == "object" then ((keys - ["_comment"]) | length) > 0 else true end)]' "$config" 2>/dev/null)" \
  || { echo "config $config: fleet.daemons is not a list" >&2; exit 2; }
# Tab and newline are refused because the list is handed on as TSV, one line each.
if ! jq -e 'all(.[]; (type == "object") and ([.name, .pattern] | all(type == "string" and length > 0 and (test("[\t\n]") | not)))) and ((map(.name) | unique | length) == length)' <<<"$daemon_cfg" >/dev/null 2>&1; then
  echo "config $config: every fleet.daemons entry needs a non-empty string name and pattern (no tab or newline), and names must be unique" >&2
  exit 2
fi
daemons_expected="$(jq -r 'length' <<<"$daemon_cfg")"
# `agent-daemons.py status <agent> --json`, read once: the launchd route's daemon
# reading, and on every route the jobs the fleet runs for this agent (`configured`:
# the job's config file exists under the agent home), which is the set of followers
# the session must keep armed. It exits 1 when a job is down and still prints its
# JSON: the output is the reading, the exit code is not.
if [ -n "${AGENT_REVIVE_DAEMONS_STATUS:-}" ]; then
  daemons_status="$("$AGENT_REVIVE_DAEMONS_STATUS" status "$agent" --json 2>/dev/null)"
else
  daemons_status="$(python3 "$FLEET_ROOT/systemd/agent-daemons.py" status "$agent" --json 2>/dev/null)"
fi
cfg_dir=""
daemons_json='{}'
if [ "$daemons_expected" -gt 0 ]; then
  cfg_dir="$(resolve_config_dir)"
  while IFS=$'\t' read -r d_name d_pattern; do
    daemons_json="$(jq -c --arg n "$d_name" --argjson v "$(daemon_reading "$d_pattern" "$cfg_dir")" '. + {($n): $v}' <<<"$daemons_json")"
  done < <(jq -r '.[] | [.name, .pattern] | @tsv' <<<"$daemon_cfg")
fi
daemons_running="$(jq -c 'if any(.[]; . == null) then null else (map(select(. == true)) | length) end' <<<"$daemons_json")"

# ── follower liveness: is EACH of this agent's daemon logs followed? ───────────
# A session hears a daemon only through the follower it arms for that job
# (`agent-daemons.py follow <agent> <job>`, one per job: the scheduler's and each
# working transport's watcher). One follower down is an agent deaf to that source -
# a scheduler nobody reads, or a chat nobody hears - while the other still wakes it,
# which no substring entry in fleet.daemons can tell apart from both running. So the
# expected set is DERIVED, never configured: the jobs `status --json` reports
# `configured` for this agent (followers_expected; null when it gave no answer, and
# then nothing is read). Each is read by is_follower and follower_reading
# (followers: job -> true | false | null), and followers_down lists the ones read
# false, in EVERY state, so a working session's dead follower is not silent either.
# The launchd route reads NO follower (followers stays {}): macOS shows no process's
# environment, so nothing there could say whose session a follower serves, and a
# null per job would also block `stopped` on every Mac agent whose jobs are down.
followers_expected=null
followers_json='{}'
if jq -e '.jobs | type == "object"' <<<"$daemons_status" >/dev/null 2>&1; then
  followers_expected="$(jq -c '[.jobs | to_entries[] | select(.value.configured == true) | .key]' <<<"$daemons_status")"
  if [ "$daemon_route" != launchd ] && [ "$followers_expected" != "[]" ]; then
    [ -n "$cfg_dir" ] || cfg_dir="$(resolve_config_dir)"
    while IFS= read -r f_job; do
      [ -n "$f_job" ] || continue
      followers_json="$(jq -c --arg n "$f_job" --argjson v "$(follower_reading "$f_job" "$cfg_dir")" '. + {($n): $v}' <<<"$followers_json")"
    done < <(jq -r '.[]' <<<"$followers_expected")
  fi
fi
followers_down="$(jq -c '[to_entries[] | select(.value == false) | .key]' <<<"$followers_json")"
# ── a daemon writing to a replaced log: running, and unheard ──────────────────
# A unit opens its log once, at start. A log rewritten in place (`sed -i`) or moved
# leaves the daemon appending to the old file while its follower reads the path, so
# the session hears nothing from that job, with every unit active and every follower
# armed. `status --json` reads each job's stdout and stderr (log_replaced: the
# reason, false, or null when unreadable); only a reason counts, and only for a job
# configured for this agent. Read on BOTH routes: macOS answers through lsof.
logs_replaced='[]'
if jq -e '.jobs | type == "object"' <<<"$daemons_status" >/dev/null 2>&1; then
  logs_replaced="$(jq -c '[.jobs | to_entries[] | select(.value.configured == true and (.value.log_replaced | type) == "string") | .key]' <<<"$daemons_status")"
fi
# The jobs the session cannot hear, for the follower-down refinement below.
deaf_jobs="$(jq -c -n --argjson f "$followers_down" --argjson l "$logs_replaced" '$f + [$l[] | select(. as $j | $f | index($j) | not)]')"

if [ -n "$pane_file" ]; then
  [ -f "$pane_file" ] || { echo "no pane file at $pane_file" >&2; exit 2; }
  pane="$(cat "$pane_file")"
else
  tmpdir="$(resolve_tmpdir)"
  if ! pane="$(env -u TMUX TMUX_TMPDIR="$tmpdir" tmux capture-pane -p -t "$target" 2>/dev/null)"; then
    jq -n --arg a "$agent" --arg t "$target" --arg d "$tmpdir" \
      --argjson dm "$daemons_json" --argjson de "$daemons_expected" --argjson dr "$daemons_running" --arg m "$AUTH" \
      --argjson fo "$followers_json" --argjson fe "$followers_expected" --argjson fd "$followers_down" \
      --argjson lr "$logs_replaced" \
      '{agent:$a, state:"unreachable", signin_url:"", banner:"", note:("no tmux session " + $t + " in " + $d + " - the agent may be down, not merely logged out. Check the service unit."), pane:"",
        daemons:$dm, daemons_expected:$de, daemons_running:$dr, followers:$fo, followers_expected:$fe,
        followers_down:$fd, logs_replaced:$lr, last_turn_error:null, auth:$m}'
    exit 0
  fi
fi

# Join a URL wrapped across pane lines. ⚠️ tmux capture-pane wraps a long URL, and a
# plain `grep -oE 'https://[^ ]*'` returns only the FIRST line's fragment (measured:
# 284 of 450 chars), which authorizes as a truncated, invalid URL. So: from the
# https:// line, take everything from https:// to end-of-line, then append each
# following line that is non-empty, contains NO space, and is not the "Paste..."
# line, stopping at the first blank / spaced / Paste line.
extract_signin_url() {
  local started=0 url="" line rstripped
  while IFS= read -r line; do
    rstripped="${line%"${line##*[![:space:]]}"}"          # strip trailing whitespace
    if [ "$started" = 0 ]; then
      if grep -qE 'https://' <<<"$rstripped" && grep -qiE 'oauth|authorize' <<<"$rstripped"; then
        url="$(sed -E 's#.*(https://)#\1#' <<<"$rstripped")"
        started=1
      fi
    else
      [ -z "$rstripped" ] && break
      grep -qE '[[:space:]]' <<<"$rstripped" && break
      grep -qiE '^Paste' <<<"$rstripped" && break
      url="$url$rstripped"
    fi
  done <<<"$1"
  printf '%s' "$url"
}

# ── readings the chain below asks questions of ──────────────────────────────
# The pane TAIL is the session's live status area; everything above it is
# transcript. The distinction is the whole reason usage-cap can be trusted at all:
# a banner in the transcript is something the agent PRINTED or is DISPLAYING (a
# diff, a `cat`, a quoted line in a message it is composing), while the live status
# area is the session speaking for itself. Blank lines are dropped first because a
# captured pane is padded to the window height, so a fixed tail over the raw
# capture reads empty rows and sees nothing.
pane_tail="$(grep -v '^[[:space:]]*$' <<<"$pane" | tail -6)"

# The agents panel is the OTHER thing that can occupy the live status area, and it
# is taller than the status bar it replaces: a header, a row per agent, and a
# `↓ N more` footer when the list is clipped. Six lines is not enough to hold
# both its header and a row, so the agents-panel marker below reads a longer window
# than `pane_tail`. Twelve is what a clipped panel measures at; widening it further
# starts reading transcript, which is what `pane_tail` exists to exclude.
panel_window="$(grep -v '^[[:space:]]*$' <<<"$pane" | tail -12)"

# The error the session's last turn ended on, if the live area shows one: the LAST
# `API Error:` line in `panel_window`, with its wrapped continuation lines (indented,
# starting with a letter or digit, at most three) joined on. Read from the window, not
# the whole pane, so an error a later turn recovered from has scrolled out of it.
# Line-anchored like every other marker here - only pane decoration may precede it -
# because SKILL.md quotes the marker mid-sentence. It is a REPORTED field and decides
# no state: an idle pane after an API error is still `healthy` or `stopped` by the
# rules below, and this says why it went idle.
last_turn_error="$(awk '
    /^[[:space:]]*[^[:alnum:][:space:]]*[[:space:]]*API Error:/ {
      s = $0; sub(/^[^A]*API Error:/, "API Error:", s); cont = 1; n = 0; next }
    cont && n < 3 && /^[[:space:]]+[[:alnum:]]/ {
      t = $0; sub(/^[[:space:]]+/, "", t); s = s " " t; n++; next }
    { cont = 0 }
    END { sub(/[[:space:]]+$/, "", s); printf "%s", s }' <<<"$panel_window")"

# The sign-in prompt's marker, read once. It is hoisted out of the `signin-url`
# branch below because the agents-panel marker needs the SAME question answered, and
# two copies of this regex would drift apart in the direction of a manage panel
# drawn over a session that is actually waiting for a code.
signin_prompt=no
if grep -qiE 'Paste code here|paste the code|authorization code' <<<"$pane"; then
  signin_prompt=yes
fi

# The dead-login line, if it is the session's LAST WORD. Read once, here, because the
# two wide-window busy markers below need the answer as well as the branch does.
# ⚠️ A DEAD LOGIN BEHIND A READY PROMPT PRINTS NO SIGN-IN URL, SO NOTHING ELSE HERE
# CAN SEE IT. Every turn ends on a `<reason> · Please run /login` result at an
# ordinary ready prompt, the daemons run on under systemd, and the pane matched only
# `healthy`: a dead agent read as healthy on consecutive hourly sweeps (SKILL.md,
# Measured).
# ⚠️ WHAT CLAUDE CODE DRAWS, NOT WHAT IT SAYS. Read in the 2.1.296 binary: `Login
# expired` (and the 401 form `Please run /login · API Error: ...`) is drawn as a
# top-level message, `● ` at COLUMN 0; `OAuth token revoked` and `Not logged in` are
# drawn as a RESULT ROW, `  ⎿ ` and then a NON-BREAKING SPACE (C2 A0), hanging under
# whatever line came before. [[:space:]] does not match that byte pair in any locale,
# so the row prefix is matched as an ALTERNATION of a space and the NBSP sequence -
# never a bracket set, for the reason the agent-tree marker below gives. A pane built
# with two ASCII spaces after ⎿ is a pane Claude Code never draws.
# ⚠️ THE LINE MUST BE THE SESSION'S LAST WORD, AND THAT IS WHAT SEPARATES IT SAYING
# THE LINE FROM DISPLAYING IT. A "word" is a column-0 bullet line, or a `  ⎿` row
# that carries the drawn NBSP AND hangs under an INPUT line - a `● Monitor event`, a
# tool call (`● Name(`), a prompt echo, a `›` message. A row under an agent's own
# prose is a quote: a message body sits two columns in, exactly where a real row does,
# and the fleet's agents quote panes as their job. A quoted copy is never a word -
# a nested markdown bullet, a `cat` or `git diff` shown as tool output (its rows after
# the first are indented five), a quote mid-sentence, a row quoted in a message - and
# the decoration-class anchor the cap banner uses admits most of those, which is why
# this state does not use it. Scanning top to bottom, above the input box:
#   - a later word replaces it. Any turn draws one, so a revived session that has
#     taken a turn is clear;
#   - `Login successful` anywhere after it ends the state - the `⎿` row under a
#     `/login` echo, or the login dialog's own success screen. `Login interrupted`
#     does not: it is a cancelled login and the login is still dead;
#   - a slash-command echo (`❯ /x`) makes the rows under it command output, not
#     words, until the next column-0 line. A slash SKILL starts a turn, so a first
#     failure right under one is missed until the next wake - which draws a
#     `● Monitor event` and is read;
#   - a prompt echo (`❯ <text>`) or a `›` message clears it: a turn began after it,
#     and whatever that turn says next is the word;
#   - Remote Control's `OAuth token unavailable` notice is NOT a word either way: it
#     says the bridge's refresh gave up, which a network outage can also do, so it
#     neither proves a dead login nor clears one;
#   - a SECOND PARAGRAPH under it (a blank line, then prose indented two) marks it as
#     an agent's message whose first paragraph merely quoted the line - inline-code
#     backticks are not drawn, so such a paragraph sits at column 0. A wrapped error
#     continues on the very next line, with no blank, and is not taken for one.
# ⚠️ AND THE INPUT BOX MUST BE ON THE PANE AND HOLD THE FOCUS (`login_box`): a `❯`
# line directly under a `─` border, with no numbered selector (`❯ 1.`) drawn under
# it. The remedy types `/login` and Enter, and on a dialog that Enter is the wrong
# keystroke: the exit dialog replaces the box and is preselected on "Exit and stop
# tasks", so it KILLS the session; the login dialog replaces it too; and a dozen
# dialogs in the 2.1.296 binary (plan approval, mode switch) are drawn UNDER a box
# that stays on screen, where the Enter answers them. A dead transcript under any of
# them reads whatever else it reads (usually `unknown`), never `login-expired`.
# ⚠️ Residual, stated so nobody reads more into it: a RAW shell pane that `cat`s a
# capture at column 0, or a tool's FIRST output row that is exactly a result line, with
# the turn ended right there. A healthy turn never ends on a tool row - it ends on a
# message - so the second is transient at worst.
nbsp=$'\xc2\xa0'
# owner: what the last column-0 line was - "in" (an input: a Monitor event, a tool
# call, a prompt echo, a `›` message), "prose" (an agent's own message), "cmd" (a
# slash-command echo), "" (anything else).
login_scan="$(awk -v nb="$nbsp" '
    BEGIN { realrow = "^  ⎿ " nb }
    /^─/ { border = 1; next }
    /^❯/ && border { box = 1; border = 0; next }
    { border = 0 }
    box { if ($0 ~ /^[[:space:]]*❯ [0-9]+\./) dialog = 1; next }
    /^❯ \// { owner = "cmd"; next }
    /^(❯|›) / { word = ""; owner = "in"; next }
    /^[^[:alnum:]]*Login successful/ { word = ""; next }
    /^(●|⏺) Remote Control disconnected/ || /^  ⎿.*Remote Control disconnected/ { shut = 1; next }
    /^(●|⏺) / { word = $0; gap = 0; shut = 0; prose = 0
               owner = ($0 ~ /^(●|⏺) (Monitor event|[A-Za-z][A-Za-z0-9_]*\()/) ? "in" : "prose"; next }
    /^  ⎿/ { if (owner == "in" && $0 ~ realrow) { word = $0; gap = 0; shut = 0; prose = 0 }; next }
    /^[[:space:]]*$/ { gap = 1; next }
    word != "" && !shut && gap && /^  [^ ]/ { prose = 1; next }
    /^[^[:space:]]/ { shut = 1; if (owner == "cmd") owner = "" }
    END { printf "%s\t%d\t%d", word, prose, (box && !dialog) }' <<<"$pane")"
login_word="${login_scan%%$'\t'*}"
login_prose="$(cut -f2 <<<"$login_scan")"
login_box="$(cut -f3 <<<"$login_scan")"
login_text="$(sed -E "s/^(●|⏺) //; s/^  ⎿( |${nbsp})*//" <<<"$login_word")"
login_expired=no
if [ "$login_prose" = 0 ] \
   && grep -qE "^([A-Z][A-Za-z' -]{0,40} · Please run /login|Please run /login · .+)[[:space:]]*$" <<<"$login_text"; then
  login_expired=yes
fi

# ⚠️ A SESSION THAT IS TAKING A TURN IS NOT CAPPED AND IS NOT STUCK, whatever its
# transcript says. Two independent busy markers, both drawn in the live status
# area: the interrupt hint, and the agent-tree view with a RUNNING timer on a row.
# Without this, a pane that hit a cap, recovered and went back to work still reads
# `usage-cap` - and the remedy for usage-cap types /login into it, which blocks a
# working session on a sign-in it never needed. The markers are looked for in the
# TAIL only, because this skill and its charters quote both of them verbatim in
# prose an agent may well have on its screen.
busy=no
if grep -qF 'esc to interrupt' <<<"$pane_tail"; then
  busy=yes
elif grep -qE '(├|└|│)[[:space:]]*(◯|◉|●|○)' <<<"$pane_tail" \
  && grep -qE '[0-9]+[hms] [0-9]+[ms]' <<<"$pane_tail"; then
  busy=yes
fi

# The usage-limit banner, if the pane carries one. ⚠️ THE LIMIT NAME IS MATCHED AS
# A SHAPE, NOT AS A LIST. Claude Code builds the line as "You've hit your <limit
# name> limit", and the name varies with the plan and the model: a session window,
# a weekly window, a per-MODEL window carrying the model's name, a spend cap, and
# sometimes nothing at all ("You've hit your limit"). Two sibling builders say the
# same thing differently ("You've hit your team's shared budget", "You're out of
# usage credits"). An enumeration of the names we happen to know today goes stale
# the day a new plan or model ships, and it goes stale as a false NEGATIVE - the
# agent sits capped and classifies `healthy`, which is the exact silence this state
# exists to break.
# ⚠️ `fast limit` IS EXCLUDED ON PURPOSE AND MUST STAY EXCLUDED: it is the Fast-mode
# cooldown, it resets in MINUTES, and the session keeps taking turns throughout. It
# is not a quota cap, and treating it as one spends a human and an account switch
# on an agent that is working.
cap_banner=""
if cap_lines="$(grep -E "^[[:space:]]*[^[:alnum:]]*[[:space:]]*(You've (hit|reached) your ([A-Za-z][A-Za-z' -]{0,30} )?limit|You've hit your team's shared budget|You're out of usage credits)" <<<"$pane")"; then
  cap_banner="$(grep -vE 'fast limit' <<<"$cap_lines" | head -1)"
  cap_banner="$(sed -E "s/^[[:space:]]*[^[:alnum:]\"]*[[:space:]]*//" <<<"$cap_banner")"
fi

# ⚠️ THE THIRD BUSY MARKER: THE AGENTS PANEL, IN EITHER OF ITS TWO LAYOUTS.
#   - MANAGE mode: the panel is open rather than the prompt - a `↑/↓ to select`
#     header over rows like `❯ ● main` and `  ○ software-engineer  <what it is doing>
#     1h 26m 55s · ↓ 269.4k tokens`. It REPLACES the status bar, exactly as the
#     agent-tree view does, so a pane showing only this panel carries no status bar,
#     no banner and no prompt: without this marker it classifies `unknown`, and an
#     hourly liveness sweep reads a hard-working agent as a pane nobody could
#     interpret. That is measured, not hypothetical.
#   - LIST mode: the same rows drawn BELOW the prompt box and its status bar, which
#     then ends in `· ↓ to manage`. The status bar is no longer the bottom of the
#     pane, so the interrupt hint in it can sit above the six-line `pane_tail` and go
#     unseen - and a working session with its own transcript on screen falls through
#     to whatever loose signature that transcript happens to satisfy. Measured on a
#     live agent discussing a scrolling bug: it read `scroll-prompt`, whose remedy
#     TYPES INTO THE PANE (fixtures/working-panel-scroll-prose.txt).
# ⚠️ BOTH HALVES ARE REQUIRED AND THE MATCH IS LINE-ANCHORED, for the regime reason
# every marker here carries: SKILL.md now quotes the header verbatim, and a header or
# a footer alone would classify an agent READING this skill as working - which
# SUPPRESSES a real cap on that agent. A running timer on a glyph row is what
# separates the panel from prose about the panel. The footer is anchored to the END
# of its line because that is where the status bar draws it; the transcript's own
# `(↓ to manage)` hints end in a parenthesis and are not taken.
# ⚠️ AND THE ROWS ARE READ ONLY BELOW THE LAST HEADER OR FOOTER LINE, never
# anywhere in the window. `●` is also the bullet on every assistant message, and the
# footer is on screen whenever ANY background task runs - a Monitor included, which
# fleet agents keep armed permanently - so an idle session whose last message
# mentions a duration (`● Suite green in 12m 40s`) read `working` off its own
# transcript sitting above the status bar. An idle agent read as working is the
# agent a post-handover nudge skips. In both layouts the real rows are drawn UNDER
# the line that announces them.
# ⚠️ A panel taller than the window pushes its header or footer out of it, and the
# pane then reads `healthy` - the cheap direction, since nothing is typed on it.
# ⚠️ AND IT MAY NOT SUPPRESS A CAP, A SIGN-IN OR A DEAD LOGIN. The interrupt hint and
# the tree row are drawn BY a turn in flight; this panel is a VIEW that stays on
# screen whether or not the session is still taking turns, so it is weaker evidence
# and must not answer the three questions whose false negatives are expensive - a
# capped agent parked for days, a session sitting at a code prompt, and a session
# whose every turn fails on its login. Deleting any guard buys nothing and costs
# exactly that one.
panel_rows="$(awk '/^[[:space:]]*↑\/↓ to select|· ↓ to manage[[:space:]]*$/ { rows = ""; seen = 1; next }
                   seen { rows = rows $0 "\n" }
                   END { printf "%s", rows }' <<<"$panel_window")"
agents_panel=no
if [ -z "$cap_banner" ] && [ "$signin_prompt" = no ] && [ "$login_expired" = no ] \
   && grep -qE '^[^[:alnum:]]*(◯|◉|●|○).*[0-9]+[hms] [0-9]+[ms]' <<<"$panel_rows"; then
  agents_panel=yes
fi
if [ "$agents_panel" = yes ]; then
  busy=yes
fi

# ⚠️ THE FOURTH BUSY MARKER: THE LIVE SPINNER, e.g. `· Scurrying… (19s · ↓ 691
# tokens)`. It is drawn by a turn in flight directly above the prompt box and is
# replaced, not left behind, when the turn ends - the lines a finished turn leaves in
# the transcript (`✻ Worked for 3m 2s`, `✻ Waiting for 1 background agent to finish`)
# carry no parenthesised token count, which is what the match requires. It is read
# from `panel_window` rather than `pane_tail` because an agents panel under the
# prompt pushes it above the six-line tail - the same displacement that hides the
# interrupt hint. The wider window reads more transcript, so it takes the panel's
# guards: it may not suppress a cap banner, a code prompt or a dead login.
if [ -z "$cap_banner" ] && [ "$signin_prompt" = no ] && [ "$login_expired" = no ] \
   && grep -qE '^[^[:alnum:]]*[A-Z][a-z]+(…|\.\.\.) \(([0-9]+[hms] ?)+ · (↓|↑) [0-9.]+k? tokens' <<<"$panel_window"; then
  busy=yes
fi

# A selector option line: pane decoration, then an optional option number, then the
# option text. Used only by `adjacent_options` below.
opt_prefix='^[[:space:]]*[^[:alnum:]]*[[:space:]]*([0-9]+[.)][[:space:]]+)?'
# adjacent_options PANE ERE_A ERE_B - true iff some line matching A has a DIFFERENT
# line directly above or below it matching B. The regexes use `[(]`/`[)]` rather than
# `\(`: awk -v processes backslash escapes, and an escaped parenthesis arrives as a
# bare one - an unbalanced group. POSIX awk, no gawk extensions.
adjacent_options() {
  awk -v a="$2" -v b="$3" '
    { l[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++)
        if (l[i] ~ a && ((i > 1 && l[i-1] ~ b) || (i < NR && l[i+1] ~ b))) exit 0
      exit 1
    }' <<<"$1"
}

state="unknown"; signin_url=""; note=""; banner=""

if grep -qiE 'Claude account with subscription' <<<"$pane" \
   && grep -qiE 'Anthropic Console account|API usage billing|API key' <<<"$pane"; then
  state="auth-method"
  note="Login-method menu. Send Enter on option 1 'Claude account with subscription' (cursor defaults there). NEVER arrow to option 2 (Anthropic Console / API usage billing) - it bills per token against our budget on every turn."
elif [ "$signin_prompt" = yes ]; then
  state="signin-url"
  signin_url="$(extract_signin_url "$pane")"
  note="A sign-in URL is printed and the session waits for a code. ⚠️ Regenerate a FRESH url (SKILL.md step 3) - the one shown is usually stale, and EVERY send to a human carries a newly regenerated one. ⚠️ WHICH regeneration route depends on how this prompt was reached, and the pane cannot tell you: an expired login takes ONE Escape (prints 'Login interrupted', back at the ready prompt) and then /login + Enter, while a prompt reached from a CAPPED prompt via /login takes /login again and NEVER Escape or Ctrl-C - on that pane either one cancels the session's automatic continue at the reset time, which has no undo. Unknown origin -> try /login first; ignored (no auth-method within ~10 s) means not capped, and Escape is then safe. NEVER a double Ctrl-C on this prompt: it quits Claude Code. Sign in via a real browser (human), then paste the whole code (with its #... tail) back."
# ⚠️ status-modal is checked BEFORE healthy on purpose: the /status block is drawn
# OVER a live session, so the ready status bar is still on the pane underneath and
# the healthy branch would swallow it. Getting this order wrong is how a modal left
# open on another agent's pane reads as "healthy, nothing to do" - and a modal left
# open is what makes the next person think the session is stuck.
# ⚠️ THE MATCH IS LINE-ANCHORED, COLON-TERMINATED AND CASE-SENSITIVE, AND IT MUST
# STAY THAT WAY. A substring match on "login method" and "organization" anywhere on
# the pane classifies an agent DISCUSSING those words as a modal - including an
# agent reading this very skill - and the prescribed remedy for status-modal is to
# send Escape, which INTERRUPTS a live turn. The false positive is therefore
# destructive, and its most likely victim is someone working on this file. Failing
# the other way is harmless: an unmatched modal falls through to `healthy`.
elif grep -qE '^[[:space:]]*[^[:alnum:]]*[[:space:]]*Login method:' <<<"$pane" \
   && grep -qE '^[[:space:]]*[^[:alnum:]]*[[:space:]]*Organization:' <<<"$pane"; then
  state="status-modal"
  note="The /status block is open. ⚠️ If a usage-limit banner is ALSO on this pane, Escape cancels the session's automatic continue at the reset time - read the pane before dismissing anything. Take the account from its 'Email:' line (the 'Organization:' line is derived and on a real Workspace account often shows the org NAME, not the email), then DISMISS IT with Escape and re-triage: a modal left open on an agent's pane makes the next person read a working session as stuck."
# ⚠️ login-expired IS CHECKED AFTER signin-url AND status-modal, AND BEFORE usage-cap,
# working, healthy (and so stopped). Each edge is a decision:
#   - signin-url wins: a code prompt is what the same pane shows once /login has run,
#     with the old result lines still above it; this state's remedy - run /login -
#     would be a step backwards from a session already waiting for its code.
#   - status-modal wins: the block is drawn over the session and its remedy is to
#     dismiss it and re-triage, which then reads this state.
#   - it beats usage-cap: the cap banner is matched anywhere on the pane and lingers
#     in the scrollback, while this line is the session's LAST word - and usage-cap's
#     wait branch is wrong on a dead login, since a session with no valid token never
#     continues by itself at any reset. Read as a cap, a dead agent waits forever.
#   - working wins only on the markers a turn DRAWS (the interrupt hint, a tree row
#     with a running timer, both in the tail); the agents panel and the spinner may
#     not suppress it (their guards above).
#   - it beats healthy, which it otherwise is - it requires the input box on the pane
#     (`login_box`) - and so it is never refined into stopped: a wake line typed into a
#     logged-out session ends on one more `Login expired`. The daemon reading still
#     travels in the object; the step 11 nudge after the sign-in re-arms what is
#     missing. With no input box (a dialog, a manage panel) the pane falls through to
#     whatever else it reads, usually `unknown`.
# ⚠️ ON A TOKEN OR API-KEY AGENT THE SAME LAST WORD IS `token-invalid`, AND ITS
# REMEDY IS THE OPPOSITE OF login-expired's. Measured 2026-11-06 on 2.1.317: a session
# started with an invalid CLAUDE_CODE_OAUTH_TOKEN ends its turn on `Please run /login
# · API Error: 401 OAuth access token is invalid.` - exactly the login-expired shape.
# But /login cannot fix it: the session keeps the token its environment gave it over
# any stored sign-in, so a browser sign-in typed into it changes nothing, and the
# reviver would report an agent revived that is still dead. A separate state, so no
# caller reaches the /login remedy by habit.
elif [ "$login_expired" = yes ] && [ "$login_box" = 1 ] && [ "$busy" = no ] \
     && { [ "$AUTH" = token ] || [ "$AUTH" = api-key ]; }; then
  state="token-invalid"
  banner="$login_text"
  note="The session runs on a long-lived $AUTH (${AUTH_FILE}) and its last word is the dead-login line in 'banner': the $AUTH has expired or been revoked. NOT a revival: do NOT type /login - the session keeps its environment's token over any sign-in, so a browser sign-in fixes nothing. Report it to the operator (SKILL.md step 5, case 15): the account the auth file names needs a fresh token from claude setup-token, registered with pool_pick.py --register and installed with token_switch.py, which restarts the session."
elif [ "$login_expired" = yes ] && [ "$login_box" = 1 ] && [ "$busy" = no ]; then
  state="login-expired"
  banner="$login_text"
  note="The login has EXPIRED: the session's last message is the dead-login line in 'banner', at an otherwise ready prompt, so every turn it takes fails at once and no sign-in URL is on the pane. ⚠️ CONFIRM the line is the session's own last word (no later turn, no 'Login successful' under it) and READ THE INPUT LINE FIRST for unsent text - typed keys append to it. Remedy: the /login route at the ready prompt (SKILL.md step 3) - type /login, Enter, then Enter on option 1 at the auth-method menu; never a Ctrl-C - a double Ctrl-C opens the exit dialog at a ready prompt and quits Claude Code on a paste-code prompt. Sign the SAME account back in by default (SKILL.md step 5): an expired login is not an account problem - unless a usage-limit banner is also on the pane, which makes it step 5, case 14. Sign in with the automated browser first (SKILL.md step 6), a human only as the fallback (step 7)."
  if [ "$AUTH" != login ]; then
    note="AUTH MODE NOT KNOWN ($AUTH_PROBLEM): /login is the remedy for a login agent ONLY - on a token or api-key agent it replaces the configured credential with a pool account's sign-in. Read FLEET_AGENT_AUTH in the agent's unit before typing anything. $note"
  fi
# ⚠️ A DEAD LOGIN WHOSE INPUT BOX IS NOT TAKING INPUT IS `unknown`, ON PURPOSE. Its
# last word says the login is dead, but a dialog or a panel holds the keys - over the
# box, in place of it, or under it - so the remedy's /login and Enter would answer
# that instead, and on the exit dialog Enter kills the session. Falling through would
# read most of these panes `healthy` (the status bar is still there), which is the
# dead agent nobody revives; `unknown` sends a person to read the pane.
elif [ "$login_expired" = yes ] && [ "$busy" = no ]; then
  state="unknown"
  note="The session's last word is a dead-login result (see 'pane'), but its input box is not taking input - a dialog or a panel is drawn over, in place of, or under it. Read the pane by hand. Do NOT type /login or Enter until the dialog is understood: Enter answers it, and on the exit dialog ('Exit and stop tasks') it kills the session."
# ⚠️ usage-cap is checked BEFORE healthy for the same structural reason
# status-modal is: the cap banner is printed ABOVE a session that is otherwise
# sitting at its ready prompt, so the pane carries the ready status bar too and the
# healthy branch swallows it. It is checked before theme-prompt and scroll-prompt
# for a second reason: those two match a selector's rendered lines, and a capped
# pane carries whatever the agent was doing when the window closed - a `cat` of a
# fixture, a quoted prompt - whose lines the decoration class admits. The reverse order
# cannot misfire - a first-run selector appears right after a login, when no cap
# banner exists. A capped agent classified `healthy` is an agent nobody revives: it
# holds its work, answers nothing and looks fine, for hours on a session cap and
# for DAYS on a weekly one. That silence is the exact failure a liveness sweep
# exists to catch, so deleting this branch does not make the sweep noisier, it
# makes it blind.
# ⚠️ THE MATCH IS LINE-ANCHORED AND CASE-SENSITIVE, like status-modal's and for the
# same reason: this skill quotes the banner verbatim. Only pane decoration -
# whitespace and non-alphanumeric glyphs - may precede it.
# ⚠️ AND THAT ANCHOR IS NOT ENOUGH ON ITS OWN, SO THIS STATE IS A TRIGGER TO LOOK,
# NEVER A LICENCE TO TYPE. Every ordinary way of QUOTING the banner - a markdown
# bullet, a blockquote, a diff hunk, a `cat` of the fixture, a message an agent is
# composing about a capped peer - begins a line with punctuation, which the anchor
# admits. The busy markers above remove the cases where the session is demonstrably
# taking a turn; they cannot remove a finished turn whose transcript happens to
# show the banner. So the note tells the operator to confirm the banner is the
# session's own live state before sending a keystroke, and the `banner` field
# carries the matched line so that confirmation costs one read rather than a second
# capture. A false positive here types /login into a healthy session and blocks it
# on a sign-in nobody needed, which is why the confirmation is part of the state
# and not an optional nicety.
elif [ -n "$cap_banner" ] && [ "$busy" = no ]; then
  state="usage-cap"
  banner="$cap_banner"
  note="Usage cap: a quota window looks exhausted and the session is not taking turns. ⚠️ CONFIRM BEFORE TYPING: the banner in the 'banner' field must be the session's OWN live state, not a line it is displaying (a diff, a cat, a message about another agent) and not a spent window it has already recovered from - read the pane once. ⚠️ THEN READ THE LIMIT NAME AND THE RESET TIME - every cap lands on this one state, so the banner is the only discriminator. A SESSION limit whose reset is imminent (within ~15 min) continues by itself on the same account: type NOTHING and poll the pane with a bounded until-loop to ~3 min past the reset. A WEEKLY cap, or a session cap whose reset is hours away, IS an expired login (SKILL.md step 5, case 14): escalate to the designated human with a FRESH sign-in URL (SKILL.md step 3, the /login route) and the NEXT account from --accounts. A model-scoped or spend cap does not follow the account, so it goes to the human as it stands. ⚠️ Send NEITHER Ctrl-C NOR Escape to a capped session: both cancel the automatic continue at the reset time, and after that the account switch is the only way back."
# ⚠️ `working` is POSITIVE evidence, which `healthy` is not: the agent-tree view
# with a running timer says the session is taking a turn right now, while a ready
# status bar says only that it is willing to. A liveness sweep wants the first. It
# is a separate state rather than a note on `healthy` because the sweep's question
# is "is this agent alive", and "ready" has already been measured to be the wrong
# answer to it (SKILL.md step 11: a revived agent sits at a ready prompt doing
# nothing until it is nudged).
# ⚠️ Without this branch a pane showing ONLY the tree view classifies `unknown`,
# because the tree replaces the status bar the healthy branch looks for - so a
# healthy, hard-working agent reads as a pane nobody could interpret. Both
# markers are required together, and in the TAIL: a tree glyph alone is a box-
# drawing character any diagram uses, and a duration alone is in every log line.
# ⚠️ EVERY GLYPH HERE IS AN ALTERNATION, NEVER A BRACKET SET, AND THE SAME GOES FOR
# THE PANEL MARKER BELOW. A bracket set of multibyte characters is a set of BYTES in
# the C locale, which is the locale a service unit and the offline test both run
# under: `[◯◉●○]` there matches a LONE 0xE2, the lead byte of ⚠ · ↓ ⏺ and most of
# the glyphs a pane is decorated with, so the marker fires on panes carrying no tree
# at all. That is a false `busy`, and a false `busy` SUPPRESSES `usage-cap` - the
# capped agent nobody revives. An alternation of whole characters matches the same
# thing in every locale.
elif [ "$busy" = yes ]; then
  state="working"
  note="The session is taking a turn right now - the live status area carries an interrupt hint, a live spinner, an agent-tree row with a running timer, or the agents panel (manage mode, or listed under the prompt) over a subagent row whose timer is running. Nothing to revive, and this is stronger evidence than 'healthy': a ready prompt means WILLING to work, this means WORKING."
# ⚠️ THE RATING SURVEY IS AN IDLE STATE, AND READ AS `unknown` IT IS EXPENSIVE.
# `unknown` is what sends a person to read a pane by hand, so without this branch a
# prompt that means "this agent is fine, press 0" arrives as "someone go look" - on
# an hourly sweep, for every agent the survey catches. It is checked AFTER the cap,
# the sign-in and the busy markers on purpose: those are states that cost hours or
# days when they are missed, and a survey drawn over any of them must not hide them.
# Failing the other way is cheap - an unmatched survey falls through to `healthy` or
# `unknown`.
#
# ⚠️ THE SIGNATURE IS THE TWO RENDERED LINES, ADJACENT, EACH ANCHORED, AND THE
# QUESTION LINE MUST CARRY ITS `(optional)` SUFFIX. Anchoring the question ALONE is
# not enough, and the reason is worth stating because it defeats comment discipline:
#   - a pane WRAPS. tmux emits a continuation at column 0, so prose about this prompt
#     that happens to wrap onto the question puts it at the start of a line with an
#     EMPTY prefix - and no amount of care about how this tree writes its comments
#     can prevent that, because it is a function of pane width.
#   - a markdown bullet or blockquote (`- "How is Claude doing this session?" ...`)
#     is all non-alphanumeric before the question, which the decoration class admits.
# Both were measured firing on prose. SKILL.md itself carries the question and
# `0: Dismiss` in that order, so the victim is an agent READING this skill - and this
# state's note tells an operator to TYPE INTO THE PANE, which makes the false
# positive destructive rather than merely noisy.
# The real render is two adjacent lines - a bullet, the message, the literal
# "(optional)"; then the option cells at marginLeft 2 - so requiring the pair
# adjacent, with the suffix, is what prose does not reproduce. Failing the other way
# is cheap: an unmatched survey falls through to `healthy` or `unknown`.
# ⚠️ NEVER WRITE THE RENDERED QUESTION LINE (question + "(optional)") DIRECTLY ABOVE
# AN OPTIONS ROW anywhere in this tree, in any file a pane may show - that is the one
# form that still fires on its own source.
elif grep -A1 -E '^[[:space:]]*[^[:alnum:]]*[[:space:]]*How is Claude doing this session\? \(optional\)[[:space:]]*$' <<<"$pane" \
   | grep -qE '^[[:space:]]*[^[:alnum:]]*[[:space:]]*1[:.)][[:space:]]*Bad.*0[:.)][[:space:]]*Dismiss'; then
  state="survey-prompt"
  note="A session-rating survey is drawn over the input. This is an IDLE state, not a revival case - the agent is fine and is waiting for an answer nobody gave it. Send 0 (Dismiss) and re-triage: env -u TMUX TMUX_TMPDIR=<tmpdir> tmux send-keys -t <target> -l -- '0'. Do NOT send a bootstrap prompt or /login to it."
# ⚠️ THE TWO FIRST-RUN SELECTORS ARE MATCHED BY THEIR OWN RENDERED LINES, NEVER BY
# WORDS ANYWHERE ON THE PANE, AND THEY ARE CHECKED AFTER `working`. Both notes tell
# an operator to TYPE into the pane, so a false positive is destructive, and the
# words are ones a working agent's transcript carries all the time: a loose
# `scroll` + `wheel|arrow|mouse` match classified a live agent that was reporting on
# a scrolling bug as `scroll-prompt` (fixtures/working-panel-scroll-prose.txt).
# Each signature is one option line with ANOTHER option line directly above or
# below it (`adjacent_options`): either order, because SKILL.md step 9 says option
# order is not guaranteed, and never the matched line standing in for its own
# neighbour - a `grep -A1 -B1 | grep` pair does exactly that, and made "two
# adjacent lines" a one-line check that a single markdown bullet satisfied.
# Only pane decoration and an option NUMBER may precede an option: the picker draws
# numbered options (`❯ 4. Dark mode (colorblind-friendly)`), exactly as the
# login-method menu does, and prose puts words there.
# ⚠️ The theme wording and option order are in the Claude Code binary (`Choose the
# text style that looks best with your terminal`; Auto (match terminal), Dark mode,
# Light mode, then each in colorblind-friendly and ANSI-colors-only form). The
# scroll selector's option text is NOT in the 2.1.281 binary - measured 2026-09-24 -
# so its signature is the wording of fixtures/scroll-prompt.txt, which is
# synthesized, not captured. If a real one ever renders differently it falls through
# to `healthy` or `unknown`, which is the cheap direction: nothing is typed.
# ⚠️ Still admitted, and the reason the state is a trigger to LOOK: a `cat` or a
# diff of a selector (`+ ❯ Scroll the terminal`) is decoration followed by option
# lines, which is all a pane shows of the real thing.
elif adjacent_options "$pane" "${opt_prefix}Dark mode [(]colorblind-friendly[)]" \
       "${opt_prefix}(Auto [(]match terminal[)]|(Dark|Light) mode)"; then
  state="theme-prompt"
  note="First-run theme selector. Choose the dark colour-blind option ('Dark mode (colorblind-friendly)'), by option TEXT."
elif adjacent_options "$pane" "${opt_prefix}Send up/down arrow keys[^[:alnum:]]*$" \
       "${opt_prefix}Scroll the terminal( [(]recommended[)])?[^[:alnum:]]*$"; then
  state="scroll-prompt"
  note="First-run scroll-behaviour selector. Choose the mode where the mouse WHEEL SCROLLS the terminal, not the mode that sends up/down arrow keys."
elif grep -qiE 'bypass permissions|for shortcuts|esc to interrupt|to cycle|Try "' <<<"$pane"; then
  state="healthy"
  note="A ready status bar is showing; the agent is alive. ⚠️ Ready is not the same as WORKING - after a revival, confirm it is processing turns (SKILL.md step 11)."
fi

# ⚠️ `stopped` REFINES `healthy` AND NOTHING ELSE. A ready status bar with every
# configured daemon absent is a session that is polling nothing: nobody's message and
# no scheduled task can reach it, so it sits idle until a person happens to look.
# The pane alone cannot tell that from a quiet hour - which is the whole reason the
# reading above exists.
#   - Only `healthy` is refined. A `working` pane is never `stopped`: a session
#     mid-turn may not have re-armed its watches yet, and the turn itself is the
#     evidence it is alive. Every other state already names its own remedy.
#   - ALL configured daemons and ALL expected followers must read false. One running
#     is something that can wake the agent, and an agent that by design runs only
#     some of the fleet's daemons must not read `stopped` while those run. A null
#     anywhere is no verdict.
#   - No daemons configured and no follower expected -> no reading -> `healthy`.
# ⚠️ `follower-down` REFINES `healthy` TOO, and only when `stopped` did not: an
# expected follower read false while something else can still wake the session. The
# agent hears one source and is deaf to the other, so it is NEVER `healthy`, and it
# needs the same remedy as `stopped`: a wake line, on which the session re-arms its
# followers. A legacy daemon entry reading true (a substring match) does not
# outweigh it. A job in logs_replaced is the same deafness with every follower
# armed (its daemon writes to a replaced log), so it raises the same state through
# deaf_jobs, with its own remedy in the note: a restart of that job's unit, which a
# wake line cannot make.
if [ "$state" = "healthy" ] && [ "$(jq -n --argjson d "$daemons_json" --argjson f "$followers_json" \
     '[$d[], $f[]] | length > 0 and all(.[]; . == false)')" = true ]; then
  state="stopped"
  missing="$(jq -r -n --argjson d "$daemons_json" --argjson f "$followers_json" \
    '[($d | keys_unsorted[]), ($f | keys_unsorted[] | "follower " + .)] | join(", ")')"
  note="The session is idle at its prompt and NONE of its daemons runs under its config dir (missing: $missing), so it is polling nothing and nothing will wake it. NOT a sign-in case: no /login, no Ctrl-C. ⚠️ READ THE PANE FIRST for unsent text in the input box - typed keys append to it and Enter sends both. The remedy is a wake line typed by whoever CONTEXT.md authorises; last_turn_error, when set, says what the last turn ended on."
elif [ "$state" = "healthy" ] && [ "$deaf_jobs" != "[]" ]; then
  state="follower-down"
  causes="" remedy=""
  if [ "$followers_down" != "[]" ]; then
    causes="not followed: $(jq -r 'join(", ")' <<<"$followers_down")"
    remedy="For a job not followed, the remedy is a wake line typed by whoever CONTEXT.md authorises, asking the session to re-arm the follower of each job named. "
  fi
  if [ "$logs_replaced" != "[]" ]; then
    causes="${causes:+$causes; }writes to a replaced log: $(jq -r 'join(", ")' <<<"$logs_replaced")"
    remedy="${remedy}A job whose daemon writes to a replaced log (its log was rewritten in place or moved, so the daemon appends to the old file while the follower reads the path) needs its unit restarted, which no wake line does: the fleet's refresh job restarts it on its next run, and a reading that outlasts that run means the refresh job is not running (fleet status names it). "
  fi
  note="The session is idle at its prompt and does NOT hear every daemon the fleet runs for it ($causes): it is deaf to that source while another can still wake it, so this is never healthy. NOT a sign-in case: no /login, no Ctrl-C. ⚠️ READ THE PANE FIRST for unsent text in the input box - typed keys append to it and Enter sends both. ${remedy}last_turn_error, when set, says what the last turn ended on."
fi

# ⚠️ THE PANE TRAVELS INSIDE THE OBJECT, NOT AS RAW TEXT ON STDERR. An `unknown` is
# the one state whose whole value is the pane itself - it is what a person is sent to
# read - so it is carried rather than dropped. Printing it raw alongside the JSON
# made a merged-stream caller see a screen of terminal decoration instead of an
# object and read the script as broken; this file emits ONE JSON object and nothing
# else, whatever the state.
pane_field=""
[ "$state" = "unknown" ] && pane_field="$pane"

jq -n --arg a "$agent" --arg s "$state" --arg u "$signin_url" --arg n "$note" --arg b "$banner" --arg p "$pane_field" \
  --argjson dm "$daemons_json" --argjson de "$daemons_expected" --argjson dr "$daemons_running" --arg e "$last_turn_error" --arg m "$AUTH" \
  --argjson fo "$followers_json" --argjson fe "$followers_expected" --argjson fd "$followers_down" \
  --argjson lr "$logs_replaced" \
  '{agent:$a, state:$s, signin_url:$u, banner:$b, note:$n, pane:$p,
    daemons:$dm, daemons_expected:$de, daemons_running:$dr, followers:$fo, followers_expected:$fe,
    followers_down:$fd, logs_replaced:$lr, last_turn_error:(if $e == "" then null else $e end), auth:$m}'
