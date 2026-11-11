#!/usr/bin/env bash
# tests/host/macos-host.sh - the macOS real-machine runbook: the fleet's launchd
# port exercised on a real Mac that has other work on it, driven over ssh from a
# control host, phase by phase.
#
# NOT a *.test.* file, so tests/run-all.sh never discovers it: it runs on another
# machine, under the rules that machine's owner sets. Everything it creates there
# is under ONE directory, ~/agent-fleet-test, every launchd label it loads starts
# com.agent-fleet-test., and its last two phases remove that directory and show
# the machine is back where the first phase found it.
#
# Usage, from anywhere in the repository, on the control host:
#
#   MACOS_HOST=<user>@<host> [MACOS_SSH_KEY=<key file>] [MACOS_FLEET_REF=<ref name>] \
#   [MACOS_EVIDENCE=<dir>] [MACOS_BUSY_WAIT=<seconds>] [MACOS_BUSY_PATTERN=<ERE>] \
#   [MACOS_KEEP_GOING=1] bash tests/host/macos-host.sh <phase>...
#
# Phases, in this order (each needs the ones before it):
#   baseline  read only: what launchd, the two launchd directories, the runner
#             jobs, /private/tmp and tmux hold before anything is created.
#             Refuses when ~/agent-fleet-test exists.
#   push      a git bundle of MACOS_FLEET_REF (a ref NAME, default HEAD, with every
#             tag) and this script go to ~/agent-fleet-test; a bare origin is made
#             of the bundle (one branch, main, at that ref) and the host checkout is
#             cloned from it, so `fleet install`, `link` and `upgrade` see a clone
#             with tags; the launchctl wrapper and the gh stub are written, and the
#             wrapper is shown to refuse every form it exists to refuse.
#   p0        the domain probe: a job bootstrapped into gui/<uid> from ssh. When
#             that fails the run stops: the Aqua domain is not reachable.
#   facts-a   launchd's answers that fleetlib.services parses: print of a missing
#             service, the last exit code after an exit and after a signal, the
#             state during the throttle, pid while not running, bootout of an
#             unloaded label, a missing log directory, print of the gui domain,
#             the environment a job gets.
#   p1        tests/run-all.sh under /bin/bash 3.2, with the Python and node
#             dependencies CI installs (pip into a venv under the test tree).
#   p2        fleet install --units all --label-prefix com.agent-fleet-test, a
#             repeat, adopt, session-check, link, the scheduler job, status,
#             check-all, pin-daemons --from a writable clone, upgrade with a gh stub.
#   p3        the daemons under launchd: the follower delivers, kill -9 is
#             reported, the guard's exit 0 stays down, refresh --dry-run names its
#             config source, a changed pinned script gets DAEMON-REFRESH,
#             pin-daemons --clear, the refresh job's kickstart writes its log.
#   p5        the session supervisor (systemd/agent-session.py) with a fake claude,
#             rendered by adding-an-agent's own agent-plist block, user form.
#   p6        the stall watchdog as a LaunchAgent (the user form), rendered by
#             adding-an-agent's watchdog-plist block: it refuses a real captured
#             prompt, respawns after kill -9, re-executes after a touch, and its
#             check reports UNPROTECTED.
#   p7        agent-revive: tmux_triage.sh on stub panes and on the plist,
#             redaction.test.mjs, the share refusal.
#   facts-b   plutil -lint of every rendered plist, the BSD forms the install's
#             printed commands use, read-only account facts, and
#             bootstrap-target.sh --check (what its sudo half would do).
#   cleanup   bootout every test label, kill the test tmux servers and any test
#             process by its pid, then remove ~/agent-fleet-test.
#   verify    read only: the baseline again, compared section by section.
#   status    read only: every test label launchd holds, with its state and pid.
# p6b, the stall watchdog as a LaunchDaemon, needs sudo and is refused here: it is
# run by hand on the machine owner's go (installation/launchd-daemon.smoke.sh of
# the stall-watchdog skill is its procedure).
#
# THE RULES IT ENFORCES, because the machine is shared:
#   * PREFLIGHT before every phase: no process whose command line matches
#     MACOS_BUSY_PATTERN, an extended regex for `pgrep -f` (default Runner.Worker,
#     a self-hosted CI runner's job in progress). The machine's owner widens it to
#     the heavy build and test tools that machine runs outside CI, e.g.
#     MACOS_BUSY_PATTERN='Runner.Worker|xcodebuild|<your test runner>'. A busy
#     machine is waited for, at most MACOS_BUSY_WAIT seconds (default 1800), then
#     the run stops with exit 75 and nothing of that phase ran. The same check
#     after a phase says whether a job started during it.
#   * EVERY launchctl CALL THAT NAMES A JOB goes through the wrapper, a `launchctl`
#     in the bin directory of the test HOME, which is FLEET_LAUNCHCTL and first on
#     PATH for every command the phases run. It passes a com.agent-fleet-test.*
#     label in gui/<uid>, a plist under ~/agent-fleet-test whose Label carries that
#     prefix, and reads; anything else is refused with exit 64, `enable` and
#     `disable` included, since each writes a permanent override that launchd keeps
#     in a database only root can edit. baseline, verify and cleanup read
#     `launchctl list` and `print-disabled` directly: they name no job.
#   * A TEST HOME. Every command runs with HOME, TMPDIR and the XDG directories
#     under ~/agent-fleet-test, so host.json, ~/.local/bin, the npm and pip caches
#     and ~/Library/LaunchAgents are the test's own. launchd itself starts a job
#     with the user's REAL home (facts-a prints it). A job finds this test's
#     host.json through the FLEET_HOST_CONFIG its plist names, but reads the
#     LaunchAgents of the real home: the refresh job finds none of this test's
#     jobs there and refreshes nothing, which is what p3 reports.
#   * NO BROWSER. PLAYWRIGHT_BROWSERS_PATH names an empty directory for every
#     command, so the sign-in driver's browser tests have no browser to start (they
#     report NO VERDICT, which p1 expects).
#
# Evidence: each phase's output is appended to $MACOS_EVIDENCE/<phase>.log
# (default /tmp/fleet-macos-host-evidence). Each check prints PASS or FAIL, an
# EVIDENCE line carries a measured value, and each phase ends with
# `PHASE <name> PASS` or `PHASE <name> FAIL (<n> failed)`.
#
# A failed phase stops the run, unless MACOS_KEEP_GOING is set: then a phase from
# facts-a on that reports FAIL is recorded and the next one runs, so cleanup and
# verify still run after a defect. baseline, push, p0 and cleanup always stop it.
#
# Exit codes: 0 every phase passed; 1 a phase failed; 2 usage or refused; 75 the
# machine stayed busy, and nothing of that phase ran.
#
# Portable bash: the remote half runs under macOS's /bin/bash 3.2 with BSD tools.
set -u

TAB="$(printf '\t')"
PREFIX=com.agent-fleet-test
AG=ada-test
IDENT_NAME="Viktor Korsun"
IDENT_EMAIL=3628395+bitekas@users.noreply.github.com
UPGRADE_TAG=v1.0.90

die() { echo "macos-host: $*" >&2; exit 2; }

# =========================================================================
# REMOTE HALF: runs on the Mac (`--remote <phase>`)
# =========================================================================

remote_env() {
  U="$(id -u)"; ME="$(id -un)"
  REAL_HOME="$HOME"
  local pw
  pw="$(/usr/bin/dscl . -read "/Users/$ME" NFSHomeDirectory 2>/dev/null | sed 's/^NFSHomeDirectory: //')"
  [ -n "$pw" ] && [ "$pw" = "$REAL_HOME" ] || die "HOME=$HOME is not $ME's home ($pw): refusing"
  R="$REAL_HOME/agent-fleet-test"
  F="$R/fleet"; H="$R/home"; A="$R/agents"; TT="$R/tmp"; RB="$R/runbook"
  P="$PREFIX"
  PY=/opt/homebrew/bin/python3
  GIT=/opt/homebrew/bin/git; [ -x "$GIT" ] || GIT=/usr/bin/git
  TMUX_BIN=/opt/homebrew/bin/tmux
  NODE_BIN="${MACOS_NODE_BIN:-$(ls -d "$REAL_HOME"/.nvm/versions/node/v22*/bin 2>/dev/null | tail -1)}"
  TPATH="$H/bin:$H/.local/bin:${NODE_BIN:+$NODE_BIN:}/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  LC="$H/bin/launchctl"
  SOCKDIR="$A/run/claude-tmux-$AG"
  W="$A/$AG/work"
  fails=0
}

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }
ev() { echo "EVIDENCE $*"; }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
show() { sed 's/^/  | /'; }
phase_end() {
  if [ "$fails" -eq 0 ]; then echo "PHASE $1 PASS"; exit 0; fi
  echo "PHASE $1 FAIL ($fails failed)"; exit 1
}
waitfor() {  # waitfor <secs> <command...>: poll every half second until it succeeds
  local end=$((SECONDS + $1)); shift
  while [ "$SECONDS" -lt "$end" ]; do "$@" && return 0; sleep 0.5; done
  "$@"
}

# Every command a phase runs, in the test environment; tx execs it (a background
# job whose $! must be the command's own pid).
TENV_UNSET="-u TMUX -u FLEET_HOST_CONFIG -u FLEET_CONTEXT_ROOT -u CLAUDE_CONFIG_DIR -u FLEET_LEAK_DENY_FILE -u GITHUB_ACTIONS"
t() {
  env $TENV_UNSET HOME="$H" TMPDIR="$TT/" XDG_CONFIG_HOME="$H/.config" XDG_STATE_HOME="$H/.local/state" \
    XDG_DATA_HOME="$H/.local/share" XDG_CACHE_HOME="$H/.cache" PATH="$TPATH" FLEET_LAUNCHCTL="$LC" \
    FLEET_PYTHON="$PY" PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH="$TT/no-browser" \
    LANG=en_US.UTF-8 GIT_CONFIG_NOSYSTEM=1 HOMEBREW_NO_AUTO_UPDATE=1 "$@"
}
tx() {
  exec env $TENV_UNSET HOME="$H" TMPDIR="$TT/" XDG_CONFIG_HOME="$H/.config" XDG_STATE_HOME="$H/.local/state" \
    XDG_DATA_HOME="$H/.local/share" XDG_CACHE_HOME="$H/.cache" PATH="$TPATH" FLEET_LAUNCHCTL="$LC" \
    FLEET_PYTHON="$PY" PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH="$TT/no-browser" \
    LANG=en_US.UTF-8 GIT_CONFIG_NOSYSTEM=1 HOMEBREW_NO_AUTO_UPDATE=1 "$@"
}

lcp() { "$LC" print "gui/$U/$1" 2>&1; }
lcf() { lcp "$1" | sed -n "s/^${TAB}$2 = //p" | head -1; }
top() { lcp "$1" | grep "^${TAB}[^${TAB}]" | grep -v -e ' = {$' -e "^${TAB}}\$" | sed "s/^${TAB}/    /"; }
running() { [ "$(lcf "$1" state)" = running ] && [ -n "$(lcf "$1" pid)" ]; }
notfound() { lcp "$1" | grep -q "Could not find service"; }
newpid() { local p; p="$(lcf "$1" pid)"; [ -n "$p" ] && [ "$p" != "$2" ] && [ "$(lcf "$1" state)" = running ]; }
mkplist() {  # mkplist <path> <label> <json of the other keys>
  "$PY" -c 'import json, plistlib, sys
d = json.loads(sys.argv[3]); d["Label"] = sys.argv[2]
with open(sys.argv[1], "wb") as f:
    plistlib.dump(d, f)' "$1" "$2" "$3"
}
plistval() {  # plistval <path> <python expression over d>
  "$PY" -c 'import plistlib, sys
d = plistlib.load(open(sys.argv[1], "rb"))
print(eval(sys.argv[2]))' "$1" "$2"
}
skill_block() {  # skill_block <fenced block name> <first line> <out>: adding-an-agent's block, first line filled
  "$PY" - "$F/.claude/skills/adding-an-agent/SKILL.md" "$1" "$2" "$3" <<'EOF'
import re, sys
md, name, first, out = sys.argv[1:]
lines, body, indent = open(md, encoding="utf-8").read().split("\n"), None, ""
for line in lines:
    if body is None:
        m = re.fullmatch(r"(\s*)```bash " + re.escape(name) + r"\s*", line)
        if m:
            body, indent = [], m.group(1)
        continue
    if line.strip() == "```":
        break
    body.append(line[len(indent):] if line.startswith(indent) else line)
if not body:
    sys.exit(f"no ```bash {name} block in {md}")
body[0] = first
open(out, "w").write("\n".join(body) + "\n")
EOF
}

r_preflight() {  # r_preflight <ERE>: exit 75 and the matches while anything matches
  local busy
  [ -n "${1:-}" ] || die "preflight needs the busy pattern"
  busy="$(pgrep -fl "$1")"
  if [ -n "$busy" ]; then echo "$busy"; exit 75; fi
  echo idle
  exit 0
}

r_snapshot() {  # the sections baseline and verify print, compared by the local half
  echo "== list_count"; /bin/launchctl list | grep -c agent-fleet-test
  echo "== print_disabled"; /bin/launchctl print-disabled "gui/$U" | grep agent-fleet-test
  echo "== launchagents"; stat -f '%N %z %m %Sp' "$REAL_HOME/Library/LaunchAgents" "$REAL_HOME"/Library/LaunchAgents/* 2>&1
  echo "== launchdaemons"; stat -f '%N %z %m %Sp' /Library/LaunchDaemons /Library/LaunchDaemons/* 2>&1
  echo "== runners"; /bin/launchctl list | awk '$3 ~ /^actions\.runner\./ {print $1, $3}'; pgrep -fl Runner.Listener
  echo "== residue"; ls -d "$REAL_HOME/.config/agent-fleet" "$REAL_HOME/.local/state/agent-fleet" \
    "$REAL_HOME/.local/bin/fleet" "$REAL_HOME/.local/bin/claude-attach" "$REAL_HOME/.local/bin/gitleaks" \
    "$REAL_HOME"/Library/LaunchAgents/com.agent-fleet* /Library/LaunchDaemons/com.agent-fleet* 2>&1 | sed 's/^ls: //'
  echo "== tmp_mine"; find /private/tmp -maxdepth 1 -user "$U" -print 2>/dev/null | sort
  echo "== user_tmp"; ls -A "$(getconf DARWIN_USER_TEMP_DIR)" 2>/dev/null | grep -E '^(fleet|wdl\.|wds\.|fas-|tmux-|agent-fleet)' | sort
  echo "== tmux"; pgrep -fl tmux
  echo "== test_root"; ls -d "$R" 2>&1 | sed 's/^ls: //'
  echo "== pgrep_test"; pgrep -fl agent-fleet-test
  echo "== df"; df -h "$REAL_HOME" | tail -1
  echo "== end"
}

r_baseline() {
  [ ! -e "$R" ] || die "$R exists: not this run's to use (a previous run was not cleaned up, or it is someone else's)"
  ev "macOS $(sw_vers -productVersion) $(uname -m), uid $U, launchctl managername from ssh: $(/bin/launchctl managername)"
  r_snapshot
  phase_end baseline
}

r_verify() {
  r_snapshot
  echo "-- checks"
  check "nothing named agent-fleet-test in launchctl list" [ "$(/bin/launchctl list | grep -c agent-fleet-test)" = 0 ]
  check "no agent-fleet-test override in print-disabled gui/$U" [ -z "$(/bin/launchctl print-disabled "gui/$U" | grep agent-fleet-test)" ]
  check "no process names agent-fleet-test" [ -z "$(pgrep -f agent-fleet-test)" ]
  check "$R is gone" [ ! -e "$R" ]
  phase_end verify
}

write_wrapper() {
  cat > "$LC" <<'EOF'
#!/bin/bash
# launchctl wrapper of the agent-fleet macOS runbook (tests/host/macos-host.sh).
# It passes a call to the real launchctl only when the call names a
# com.agent-fleet-test.* label in this user's gui domain, loads a plist under the
# runbook's directory whose Label carries that prefix, or only reads. Anything else
# is refused with exit 64, before launchctl runs. enable and disable are refused
# too: each writes an override launchd keeps for good. Every call is logged.
REAL="${LAUNCHCTL_WRAPPER_REAL:-/bin/launchctl}"
P=com.agent-fleet-test.
ROOT=@ROOT@
LOG=@ROOT@/runbook/launchctl.log
U="$(id -u)"
note() { printf '%s %s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$*" >> "$LOG"; }
refuse() { note "REFUSED $*"; echo "launchctl wrapper: REFUSED (names no ${P}* job in gui/$U): launchctl $*" >&2; exit 64; }
job() { case "$1" in "gui/$U/$P"?*) return 0 ;; esac; return 1; }
readable() { case "$1" in "gui/$U"|"gui/$U/$P"?*|"system/$P"?*) return 0 ;; esac; return 1; }
plist() {
  case "$1" in "$ROOT"/*) ;; *) return 1 ;; esac
  case "$1" in *..*) return 1 ;; esac
  l="$(/usr/bin/plutil -extract Label raw -o - "$1" 2>/dev/null)" || return 1
  case "$l" in "$P"?*) return 0 ;; esac
  return 1
}
[ $# -ge 1 ] || refuse "(no arguments)"
case "$1" in
  list|managername) [ $# -eq 1 ] || refuse "$@" ;;
  print) [ $# -eq 2 ] && readable "$2" || refuse "$@" ;;
  print-disabled) [ $# -eq 2 ] && [ "$2" = "gui/$U" ] || refuse "$@" ;;
  bootstrap) [ $# -eq 3 ] && [ "$2" = "gui/$U" ] && plist "$3" || refuse "$@" ;;
  bootout)
    if [ $# -eq 2 ] && job "$2"; then :
    elif [ $# -eq 3 ] && [ "$2" = "gui/$U" ] && plist "$3"; then :
    else refuse "$@"; fi ;;
  kickstart)
    last=""; flags_ok=1; i=0
    for a in "$@"; do
      i=$((i + 1)); last="$a"
      if [ "$i" -gt 1 ] && [ "$i" -lt $# ]; then case "$a" in -k|-p|-s) ;; *) flags_ok=0 ;; esac; fi
    done
    [ $# -ge 2 ] && [ "$flags_ok" = 1 ] && job "$last" || refuse "$@" ;;
  kill) [ $# -eq 3 ] && job "$3" || refuse "$@" ;;
  blame) [ $# -eq 2 ] && job "$2" || refuse "$@" ;;
  *) refuse "$@" ;;
esac
note "RUN${LAUNCHCTL_WRAPPER_REAL:+ (to a stub)} $*"
"$REAL" "$@"
rc=$?
note "EXIT $rc $1 ${2:-}"
exit $rc
EOF
  sed "s|@ROOT@|$R|g" "$LC" > "$LC.new" && mv "$LC.new" "$LC"
  chmod 755 "$LC"
}

write_gh_stub() {
  cat > "$H/bin/gh-stub" <<'EOF'
#!/bin/bash
# FLEET_GH stub of the agent-fleet macOS runbook: answers `gh api
# repos/<owner>/<repo>/commits/<sha>/check-runs...` with the four CI checks fleet
# upgrade requires; STUB_CI=fail makes the leak check a failure. Anything else is
# refused.
case "$*" in "api repos/"*"/check-runs"*) ;; *) echo "gh stub: not a check-runs call: $*" >&2; exit 2 ;; esac
echo "$*" >> @ROOT@/runbook/gh-stub.log
leak=success
[ "${STUB_CI:-ok}" = fail ] && leak=failure
printf '{"check_runs":[%s,%s,%s,%s]}\n' \
  '{"id":1,"name":"test","status":"completed","conclusion":"success"}' \
  '{"id":2,"name":"gates","status":"completed","conclusion":"success"}' \
  "{\"id\":3,\"name\":\"leak\",\"status\":\"completed\",\"conclusion\":\"$leak\"}" \
  '{"id":4,"name":"commit-hygiene","status":"completed","conclusion":"success"}'
EOF
  sed "s|@ROOT@|$R|g" "$H/bin/gh-stub" > "$H/bin/gh-stub.new" && mv "$H/bin/gh-stub.new" "$H/bin/gh-stub"
  chmod 755 "$H/bin/gh-stub"
}

wrapper_selftest() {
  local stub="$TT/launchctl-stub" sp="$TT/selftest.plist" rp out rc
  printf '#!/bin/sh\necho "STUB-REACHED $*"\n' > "$stub"
  chmod 755 "$stub"
  mkplist "$sp" "$P.selftest" '{"ProgramArguments": ["/usr/bin/true"]}'
  mkplist "$TT/other.plist" "com.example.selftest" '{"ProgramArguments": ["/usr/bin/true"]}'
  rp="$(ls "$REAL_HOME"/Library/LaunchAgents/*.plist 2>/dev/null | head -1)"
  refused() {
    out="$(LAUNCHCTL_WRAPPER_REAL="$stub" "$LC" "$@" 2>&1)"; rc=$?
    if [ "$rc" -eq 64 ] && ! echo "$out" | grep -q STUB-REACHED; then pass "wrapper refuses: launchctl $*"
    else fail "wrapper refuses: launchctl $* (exit $rc: $out)"; fi
  }
  passed() {
    out="$(LAUNCHCTL_WRAPPER_REAL="$stub" "$LC" "$@" 2>&1)"; rc=$?
    if [ "$rc" -eq 0 ] && [ "$out" = "STUB-REACHED $*" ]; then pass "wrapper passes: launchctl $*"
    else fail "wrapper passes: launchctl $* (exit $rc: $out)"; fi
  }
  echo "-- the wrapper, against a stub launchctl"
  refused
  refused bootout "gui/$U"
  refused bootout "gui/$U/"
  refused bootout "gui/$U/$P."
  refused bootout "gui/$U/actions.runner.example"
  refused bootout system
  refused bootout "system/$P.selftest"
  refused bootout "user/$U/$P.selftest"
  [ -n "$rp" ] && refused bootstrap "gui/$U" "$rp"
  refused bootstrap "gui/$U" "$TT/other.plist"
  refused bootstrap system "$sp"
  refused bootstrap "gui/$U" "$TT/../tmp/selftest.plist"
  refused kickstart -k "gui/$U/com.apple.Finder"
  refused kickstart -k "gui/$U"
  refused kickstart -x "gui/$U/$P.selftest"
  refused kill 9 "gui/$U/com.apple.Finder"
  refused enable "gui/$U/$P.selftest"
  refused disable "gui/$U/$P.selftest"
  refused remove "$P.selftest"
  refused load "$sp"
  refused unload "$sp"
  refused print-disabled system
  refused print "gui/$U/com.apple.Finder"
  refused print system
  refused setenv X 1
  passed list
  passed print "gui/$U"
  passed print "gui/$U/$P.selftest"
  passed print "system/$P.selftest"
  passed print-disabled "gui/$U"
  passed bootstrap "gui/$U" "$sp"
  passed bootout "gui/$U/$P.selftest"
  passed bootout "gui/$U" "$sp"
  passed kickstart -k "gui/$U/$P.selftest"
  passed kill TERM "gui/$U/$P.selftest"
  rm -f "$stub" "$sp" "$TT/other.plist"
}

r_setup() {
  local sha="${1:-}" b
  [ -n "$sha" ] || die "setup needs the commit"
  [ -d "$RB" ] && [ -f "$TT/fleet.bundle" ] || die "push has not copied the bundle to $TT"
  mkdir -p "$H/bin" "$H/.config" "$H/.local/bin" "$H/Library/LaunchAgents" "$A" "$TT/no-browser"
  t "$GIT" -c init.defaultBranch=main clone -q --bare "$TT/fleet.bundle" "$TT/origin.git" || fail "bare origin from the bundle"
  t "$GIT" -C "$TT/origin.git" update-ref refs/heads/main "$sha"
  t "$GIT" -C "$TT/origin.git" symbolic-ref HEAD refs/heads/main
  for b in $(t "$GIT" -C "$TT/origin.git" for-each-ref --format='%(refname)' refs/heads/); do
    [ "$b" = refs/heads/main ] || t "$GIT" -C "$TT/origin.git" update-ref -d "$b"
  done
  t "$GIT" -c init.defaultBranch=main clone -q "$TT/origin.git" "$F" || fail "the host checkout cloned from the origin"
  check "the host checkout is at $sha" [ "$(t "$GIT" -C "$F" rev-parse HEAD 2>/dev/null)" = "$sha" ]
  ev "host checkout: $F, tags $(t "$GIT" -C "$F" tag -l | tr '\n' ' '), describe $(t "$GIT" -C "$F" describe --tags)"
  ev "tools: $($PY -V), $($TMUX_BIN -V), git $($GIT --version | awk '{print $3}'), node ${NODE_BIN:-<none>}, bash $BASH_VERSION"
  write_wrapper
  write_gh_stub
  wrapper_selftest
  phase_end setup
}

r_p0() {
  local lbl="$P.probe" pl="$H/Library/LaunchAgents/$PREFIX.probe.plist" log="$TT/p0/probe.log" out rc pid
  mkdir -p "$TT/p0"
  mkplist "$pl" "$lbl" "{\"ProgramArguments\": [\"/bin/sh\", \"-c\", \"/usr/bin/env | /usr/bin/sort; exec /bin/sleep 300\"],
    \"RunAtLoad\": true, \"StandardOutPath\": \"$log\", \"StandardErrorPath\": \"$log\"}"
  out="$("$LC" print "gui/$U" 2>&1)"; rc=$?
  ev "print gui/$U from ssh: exit $rc"
  out="$(t "$LC" bootstrap "gui/$U" "$pl" 2>&1)"; rc=$?
  ev "bootstrap gui/$U <test home>/Library/LaunchAgents/$lbl.plist: exit $rc ${out:+($out)}"
  if [ "$rc" -ne 0 ]; then
    fail "P0: ssh cannot bootstrap a job into gui/$U. STOP: decision 1 (the Aqua domain) goes to the owner"
    phase_end p0
  fi
  pass "P0: a job bootstraps into gui/$U from ssh"
  check "P0: the probe runs" waitfor 10 running "$lbl"
  pid="$(lcf "$lbl" pid)"
  ev "probe process: $(ps -o pid=,ppid=,user=,command= -p "$pid" 2>&1)"
  check "P0: it runs as $ME, a child of launchd" [ "$(ps -o user=,ppid= -p "$pid" | awk '{print $1, $2}')" = "$ME 1" ]
  echo "  print, top level:"; top "$lbl"
  waitfor 5 grep -q '^HOME=' "$log"
  ev "a gui-domain job's environment, keys: $(cut -d= -f1 "$log" | tr '\n' ' ')"
  ev "its HOME=$(sed -n 's/^HOME=//p' "$log") PATH=$(sed -n 's/^PATH=//p' "$log") SHELL=$(sed -n 's/^SHELL=//p' "$log")"
  check "P0: launchd gives the job the user's real HOME, not the caller's" [ "$(sed -n 's/^HOME=//p' "$log")" = "$REAL_HOME" ]
  out="$(t "$LC" bootout "gui/$U/$lbl" 2>&1)"; rc=$?
  ev "bootout gui/$U/$lbl: exit $rc ${out:+($out)}"
  check "P0: bootout unloads it" waitfor 10 notfound "$lbl"
  check "P0: the probe process is gone" waitfor 5 eval "! kill -0 $pid 2>/dev/null"
  rm -f "$pl"
  phase_end p0
}

r_facts_a() {
  local d="$TT/facts" out rc pid i l
  mkdir -p "$d"
  echo "-- print of a service launchd does not hold"
  out="$("$LC" print "gui/$U/$P.fact-missing" 2>&1)"; rc=$?
  ev "print gui/$U/$P.fact-missing: exit $rc, text: $(echo "$out" | tr '\n' ' ')"

  echo "-- a job that exits 3 (no KeepAlive)"
  l="$P.fact-exit3"
  mkplist "$d/exit3.plist" "$l" '{"ProgramArguments": ["/bin/sh", "-c", "exit 3"], "RunAtLoad": true}'
  t "$LC" bootstrap "gui/$U" "$d/exit3.plist"; sleep 2
  echo "  print, top level:"; top "$l"
  ev "after exit 3: state='$(lcf "$l" state)' pid='$(lcf "$l" pid)' last exit code='$(lcf "$l" "last exit code")' runs='$(lcf "$l" runs)'"
  t "$LC" bootout "gui/$U/$l"

  echo "-- a job killed by SIGTERM, then one killed by SIGKILL"
  l="$P.fact-signal"
  mkplist "$d/signal.plist" "$l" '{"ProgramArguments": ["/bin/sleep", "300"], "RunAtLoad": true}'
  t "$LC" bootstrap "gui/$U" "$d/signal.plist"
  waitfor 10 running "$l"
  pid="$(lcf "$l" pid)"; echo "  kill -TERM $pid"; kill -TERM "$pid"; sleep 1
  echo "  print, top level:"; top "$l"
  ev "after SIGTERM: state='$(lcf "$l" state)' pid='$(lcf "$l" pid)' last exit code='$(lcf "$l" "last exit code")' last terminating signal='$(lcf "$l" "last terminating signal")'"
  t "$LC" kickstart "gui/$U/$l"; waitfor 10 running "$l"
  pid="$(lcf "$l" pid)"; echo "  kill -KILL $pid"; kill -KILL "$pid"; sleep 1
  ev "after SIGKILL: state='$(lcf "$l" state)' pid='$(lcf "$l" pid)' last exit code='$(lcf "$l" "last exit code")' last terminating signal='$(lcf "$l" "last terminating signal")'"
  t "$LC" bootout "gui/$U/$l"

  echo "-- KeepAlive true, exit 1 at once, ThrottleInterval 10: the state, sampled every second"
  l="$P.fact-throttle"
  mkplist "$d/throttle.plist" "$l" '{"ProgramArguments": ["/bin/sh", "-c", "exit 1"], "RunAtLoad": true, "KeepAlive": true, "ThrottleInterval": 10}'
  t "$LC" bootstrap "gui/$U" "$d/throttle.plist"
  i=0
  while [ "$i" -lt 14 ]; do
    echo "  t+${i}s state='$(lcf "$l" state)' pid='$(lcf "$l" pid)' runs='$(lcf "$l" runs)' last exit code='$(lcf "$l" "last exit code")'"
    sleep 1; i=$((i + 1))
  done
  t "$LC" bootout "gui/$U/$l"

  echo "-- bootout of a label launchd does not hold"
  out="$("$LC" bootout "gui/$U/$P.fact-unloaded" 2>&1)"; rc=$?
  ev "bootout gui/$U/$P.fact-unloaded: exit $rc, text: $(echo "$out" | tr '\n' ' ')"

  echo "-- StandardOutPath in a directory that does not exist"
  l="$P.fact-logdir"
  mkplist "$d/logdir.plist" "$l" "{\"ProgramArguments\": [\"/bin/echo\", \"hello\"], \"RunAtLoad\": true,
    \"StandardOutPath\": \"$d/nodir/sub/out.log\", \"StandardErrorPath\": \"$d/nodir/sub/out.log\"}"
  t "$LC" bootstrap "gui/$U" "$d/logdir.plist"; sleep 2
  ev "missing log dir: created by launchd? $([ -d "$d/nodir/sub" ] && echo yes || echo no); the log: $(cat "$d/nodir/sub/out.log" 2>&1); state='$(lcf "$l" state)' last exit code='$(lcf "$l" "last exit code")' runs='$(lcf "$l" runs)'"
  t "$LC" bootout "gui/$U/$l"

  echo "-- print gui/$U (the domain), its first lines"
  out="$("$LC" print "gui/$U" 2>&1)"; rc=$?
  ev "print gui/$U: exit $rc, $(echo "$out" | wc -l | tr -d ' ') lines"
  echo "$out" | head -8 | show

  echo "-- not measured here: bootstrapping a DISABLED label (launchctl disable writes an override"
  echo "   to launchd's root-owned database that no command run without root removes; measure it"
  echo "   on a throwaway machine)"
  for l in fact-exit3 fact-signal fact-throttle fact-logdir; do
    check "facts: $P.$l is not left loaded" waitfor 10 notfound "$P.$l"
  done
  phase_end facts-a
}

r_p1() {
  local log="$RB/run-all.log" rc summary bad
  echo "-- dependencies, as ci-macos.yml installs them (into the test tree; no browser)"
  t "$PY" -m venv "$TT/venv" && t "$TT/venv/bin/python3" -m pip install -q --disable-pip-version-check \
    -r "$F/.claude/skills/google-spreadsheet/installation/requirements.txt" 2>&1 | tail -3 | show
  t npm ci --prefix "$F/.claude/skills/agent-revive/signin_driver" --no-audit --no-fund 2>&1 | tail -2 | show
  t bash "$F/tools/leak-gate/install-gitleaks.sh" "$H/.local/bin" 2>&1 | tail -2 | show
  find /private/tmp -maxdepth 1 -user "$U" -print 2>/dev/null | sort > "$RB/p1-tmp-before"
  echo "-- bash tests/run-all.sh"
  ( cd "$F" && t env PATH="$TT/venv/bin:$TPATH" /bin/bash tests/run-all.sh ) > "$log" 2>&1
  rc=$?
  find /private/tmp -maxdepth 1 -user "$U" -print 2>/dev/null | sort > "$RB/p1-tmp-after"
  show < "$log"
  ev "run-all exit $rc: $(grep '^== [0-9]* discovered' "$log")"
  comm -13 "$RB/p1-tmp-before" "$RB/p1-tmp-after" > "$RB/p1-tmp-left"
  ev "/private/tmp entries the run left (cleanup removes each that is an empty directory): $(tr '\n' ' ' < "$RB/p1-tmp-left")"
  bad="$(grep -E '^FAIL  ' "$log" | grep -v 'agent-revive/signin_driver/profiles.test.mjs  (exit 3;' )"
  check "P1: run-all.sh ran every test it discovered (none NOT RUN)" eval "! grep -q '^NOT RUN' '$log'"
  check "P1: no test failed except profiles.test.mjs's NO VERDICT (exit 3: its browser half has no browser, by the no-browser rule)" [ -z "$bad" ]
  if grep -q 'profiles.test.mjs  (exit 3;' "$log"; then
    check "P1: profiles.test.mjs's only gap is half B (no chromium), and half A had no failure" \
      eval "grep -q 'half B did not run: no chromium' '$log' && ! grep -q 'assertion(s) FAILED above' '$log'"
  fi
  phase_end p1
}

r_p2() {
  local out rc pid0 pid1 cur
  mkdir -p "$A/$AG/.claude" "$W/.claude" "$A/$AG/config" "$A/$AG/state/daemons" "$A/$AG/secrets/personal"
  cp "$F/tests/fixtures/install/.claude/fleet.json" "$W/.claude/fleet.json"
  "$PY" - "$W/.claude/fleet.json" <<'EOF'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
m["fleet"]["repo"] = "https://github.com/example/agent-fleet.git"   # upgrade reads <owner>/<repo> from it
open(p, "w").write(json.dumps(m, indent=2) + "\n")
EOF
  echo "-- fleet install --agents-root <A> --units all --label-prefix $P"
  out="$(t "$F/bin/fleet" install --agents-root "$A" --units all --label-prefix "$P" 2>&1)"; rc=$?
  echo "$out" | show
  check "P2 install: exit 0" [ "$rc" -eq 0 ]
  check "P2 install: host.json carries launchd_prefix $P and python $PY" \
    [ "$("$PY" -c 'import json, sys; h = json.load(open(sys.argv[1])); print(h.get("launchd_prefix"), h.get("python"))' "$H/.config/agent-fleet/host.json")" = "$P $PY" ]
  check "P2 install: identities.json trusts the install's upstream identity" grep -q "$IDENT_EMAIL" "$H/.config/agent-fleet/identities.json"
  check "P2 install: the claims directory is mode 700" [ "$(stat -f %Lp "$A/claims")" = 700 ]
  check "P2 install: fleet linked into the test home's ~/.local/bin" [ "$(readlink "$H/.local/bin/fleet")" = "$F/bin/fleet" ]
  check "P2 install: claude-attach linked too" [ "$(readlink "$H/.local/bin/claude-attach")" = "$F/bin/claude-attach" ]
  check "P2 install: the pinned gitleaks in the test home" eval "'$H/.local/bin/gitleaks' version | grep -q 8.30.1"
  check "P2 install: the refresh plist lints" /usr/bin/plutil -lint "$H/Library/LaunchAgents/$P.daemons-refresh.plist"
  check "P2 install: launchd holds the refresh job" eval "! notfound '$P.daemons-refresh'"
  echo "  refresh job, top level:"; top "$P.daemons-refresh"
  check "P2 install: nothing of the fleet in the real home" \
    eval "[ ! -e '$REAL_HOME/.config/agent-fleet' ] && [ ! -e '$REAL_HOME/.local/bin/fleet' ] && ! ls '$REAL_HOME'/Library/LaunchAgents/com.agent-fleet* >/dev/null 2>&1"
  out="$(t "$F/bin/fleet" install --agents-root "$A" --units all 2>&1)"; rc=$?
  echo "$out" | show
  check "P2 install, repeated: exit 0, nothing rendered, bootstrapped or restarted" \
    eval "[ $rc -eq 0 ] && ! echo \"\$out\" | grep -qE '^(rendered|bootstrapped|restarted)'"

  echo "-- fleet adopt, session-check, link"
  out="$(t fleet adopt "$W" 2>&1)"; rc=$?; echo "$out" | show
  check "P2 adopt: keeps the manifest, adds the SessionStart hook" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -q '^kept ' && echo \"\$out\" | grep -q 'SessionStart hook'"
  out="$(t env CLAUDE_CONFIG_DIR="$A/$AG/.claude" fleet session-check --project "$W" 2>&1)"; rc=$?; echo "$out" | show
  check "P2 session-check before link: exit 0, names the skills not linked for the agent's config dir" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -qF 'not linked for the config dir $A/$AG/.claude:'"
  out="$(t fleet link "$AG" 2>&1)"; rc=$?; echo "$out" | tail -3 | show
  check "P2 link: exit 0, a link per manifest skill" \
    eval "[ $rc -eq 0 ] && [ \$(ls '$A/$AG/.claude/skills' | wc -l) -eq \$('$PY' -c 'import json,sys; print(len(json.load(open(sys.argv[1]))[\"skills\"]))' '$W/.claude/fleet.json') ]"
  out="$(t env CLAUDE_CONFIG_DIR="$A/$AG/.claude" fleet session-check --project "$W" 2>&1)"; rc=$?; echo "$out" | show
  check "P2 session-check after link: exit 0 and silent" eval "[ $rc -eq 0 ] && [ -z \"\$out\" ]"

  echo "-- the scheduler job: agent-daemons.py --install $AG"
  "$PY" - "$F" "$A" "$AG" <<'EOF'
import json, sys
f, a, ag = sys.argv[1:]
c = json.load(open(f + "/.claude/skills/scheduled-tasks/config.example.json"))
c["owner"]["claude_config_dir"] = f"{a}/{ag}/.claude"
c["db"]["path"] = f"{a}/{ag}/state/scheduler/tasks.db"
open(f"{a}/{ag}/config/scheduler.json", "w").write(json.dumps(c, indent=2) + "\n")
EOF
  out="$(t "$PY" "$F/systemd/agent-daemons.py" --install "$AG" 2>&1)"; rc=$?; echo "$out" | show
  check "P2 --install: exit 0, enables the scheduler job, skips the watcher (no config)" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -q '^enabled $P.sched.$AG' && echo \"\$out\" | grep -q '^SKIPPED $P.slack-watch.$AG'"
  check "P2 --install: the scheduler job runs" waitfor 15 running "$P.sched.$AG"
  sleep 2
  pid0="$(lcf "$P.sched.$AG" pid)"
  ev "scheduler process: $(ps -o pid=,user=,command= -p "$pid0")"
  check "P2: the exec shim became the scheduler (same pid, argv python -u <host checkout>/.../sched.py)" \
    eval "ps -o command= -p $pid0 | grep -q -- '-u $F/.claude/skills/scheduled-tasks/sched.py\$'"
  check "P2: the scheduler job plist lints" /usr/bin/plutil -lint "$H/Library/LaunchAgents/$P.sched.$AG.plist"

  echo "-- fleet status $AG"
  out="$(t fleet status "$AG" 2>&1)"; rc=$?; echo "$out" | show
  ev "fleet status exit $rc"
  check "P2 status: reads the running job's script from its argv on macOS" \
    eval "echo \"\$out\" | grep -qF 'ok     $AG: $P.sched.$AG runs $F/.claude/skills/scheduled-tasks/sched.py'"
  check "P2 status: the watchdog is not installed, and says so" \
    eval "echo \"\$out\" | grep -qF 'DRIFT  $AG: $P.stall-watchdog.$AG is not installed, and the install links stall-watchdog'"
  check "P2 status: the host checkout is clean and read-only" \
    eval "echo \"\$out\" | grep -q '^ok     host checkout clean' && echo \"\$out\" | grep -q '^ok     host checkout read-only'"

  echo "-- fleet check-all $AG"
  out="$(t fleet check-all "$AG" 2>&1)"; rc=$?; echo "$out" | show
  ev "fleet check-all exit $rc"
  check "P2 check-all: every check ran on macOS (each exit 0, 1, 2 or '-'; none crashed)" \
    eval "[ -z \"\$(echo \"\$out\" | awk 'NR > 1 && \$2 !~ /^(0|1|2|-)\$/')\" ] && [ \$(echo \"\$out\" | wc -l) -gt 1 ]"

  echo "-- fleet pin-daemons $AG --from a writable clone"
  t "$GIT" clone -q "$F" "$TT/canary"
  out="$(t fleet pin-daemons "$AG" --from "$TT/canary" 2>&1)"; rc=$?; echo "$out" | show
  check "P2 pin: exit 0, the plist written, the job restarted by bootout and bootstrap" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -q '^wrote ' && echo \"\$out\" | grep -q '^restarted $P.sched.$AG (launchctl bootout, then bootstrap)'"
  check "P2 pin: the plist carries the fleet-pin mark and lints" \
    eval "grep -q 'fleet-pin:' '$H/Library/LaunchAgents/$P.sched.$AG.plist' && /usr/bin/plutil -lint '$H/Library/LaunchAgents/$P.sched.$AG.plist' >/dev/null"
  check "P2 pin: a new scheduler process" waitfor 15 newpid "$P.sched.$AG" "$pid0"
  sleep 2
  pid1="$(lcf "$P.sched.$AG" pid)"
  check "P2 pin: it runs the clone's sched.py" eval "ps -o command= -p $pid1 | grep -q -- '-u $TT/canary/.claude/skills/scheduled-tasks/sched.py\$'"
  out="$(t fleet status "$AG" 2>&1)"
  check "P2 pin: status names the pinned script outside the host checkout" \
    eval "echo \"\$out\" | grep -qF 'DRIFT  $AG: $P.sched.$AG runs $TT/canary/.claude/skills/scheduled-tasks/sched.py'"
  out="$(t fleet install --agents-root "$A" --units all 2>&1)"; echo "$out" | show
  check "P2 pin: install keeps the pinned plist and says so" eval "echo \"\$out\" | grep -q '^kept .*$P.sched.$AG.plist: pinned'"

  echo "-- fleet upgrade $UPGRADE_TAG, CI answered by a gh stub"
  t "$GIT" clone -q "$TT/origin.git" "$TT/release"
  echo "an upgrade target made by the macOS runbook" > "$TT/release/RUNBOOK-UPGRADE.txt"
  ( cd "$TT/release" && t env GIT_AUTHOR_NAME="$IDENT_NAME" GIT_AUTHOR_EMAIL="$IDENT_EMAIL" \
      GIT_COMMITTER_NAME="$IDENT_NAME" GIT_COMMITTER_EMAIL="$IDENT_EMAIL" sh -c \
      "'$GIT' add RUNBOOK-UPGRADE.txt && '$GIT' commit -q -m 'test: the runbook upgrade target' && '$GIT' tag -a $UPGRADE_TAG -m 'runbook upgrade target' && '$GIT' push -q origin HEAD:main $UPGRADE_TAG" )
  echo "sub:deny-example-not-present-anywhere" > "$TT/deny.txt"
  cur="$(t "$GIT" -C "$F" rev-parse HEAD)"
  out="$(t env STUB_CI=fail FLEET_GH="$H/bin/gh-stub" FLEET_LEAK_DENY_FILE="$TT/deny.txt" fleet upgrade "$UPGRADE_TAG" 2>&1)"; rc=$?
  echo "$out" | show
  check "P2 upgrade with a failed CI check: refused (exit 2), the checkout where it was" \
    eval "[ $rc -eq 2 ] && echo \"\$out\" | grep -q 'CI has not succeeded on $UPGRADE_TAG' && [ \"\$(t '$GIT' -C '$F' rev-parse HEAD)\" = '$cur' ]"
  out="$(t env STUB_CI=ok FLEET_GH="$H/bin/gh-stub" FLEET_LEAK_DENY_FILE="$TT/deny.txt" fleet upgrade "$UPGRADE_TAG" 2>&1)"; rc=$?
  echo "$out" | show
  check "P2 upgrade: exit 0, checked out, read-only restored, logged" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -q '^checked out $UPGRADE_TAG' && echo \"\$out\" | grep -q '^restored the read-only mode' && grep -q ' -> $UPGRADE_TAG by ' '$H/.local/state/agent-fleet/upgrades.log'"
  out="$(t fleet status "$AG" 2>&1)"
  check "P2 upgrade: status sees the checkout at $UPGRADE_TAG, clean and read-only" \
    eval "echo \"\$out\" | grep -q '^ok     host checkout .* at $UPGRADE_TAG\$' && echo \"\$out\" | grep -q '^ok     host checkout clean' && echo \"\$out\" | grep -q '^ok     host checkout read-only'"
  phase_end p2
}

r_p3() {
  local lbl="$P.sched.$AG" fo="$RB/follow.out" fpid pid out rc cfg="$A/$AG/config/scheduler.json"
  local slog="$A/$AG/state/daemons/sched.log" rlog="$H/.local/state/agent-fleet/daemons-refresh.log"
  check "P3: the scheduler job runs (from p2)" running "$lbl"
  echo "-- the follower, in the background"
  ( tx "$PY" "$F/systemd/agent-daemons.py" follow "$AG" sched --check-secs 2 --poll-secs 0.3 --max-secs 900 > "$fo" 2>&1 ) &
  fpid=$!
  echo "  follower pid $fpid"
  sleep 4

  echo "-- 1. a task due now: the scheduler fires it and the follower delivers it"
  printf 'def should_fire(now, state):\n    return {"fire": True, "state": {}, "done": True}\n' > "$TT/once.py"
  out="$(t env CLAUDE_CONFIG_DIR="$A/$AG/.claude" SCHED_CONFIG="$cfg" FLEET_CONTEXT_ROOT="$W" \
    "$PY" "$F/.claude/skills/scheduled-tasks/sched.py" add --title "runbook check" \
    --instruction "Nothing to do: the macOS runbook checks that the scheduler fires and the follower delivers." \
    --predicate-file "$TT/once.py" --origin session --requester Ada --max-fires 1 \
    --reason "The macOS real-machine runbook proves the launchd scheduler job fires a due task and its follower delivers the line; it fires once and closes." 2>&1)"; rc=$?
  echo "$out" | tail -2 | show
  check "P3 delivers: the add succeeded" [ "$rc" -eq 0 ]
  check "P3 delivers: the follower printed the scheduler's SCHED due line" waitfor 20 grep -q '^SCHED due' "$fo"

  echo "-- 2. kill -9: launchd restarts it, the follower says so"
  pid="$(lcf "$lbl" pid)"; echo "  kill -9 $pid"; kill -9 "$pid"
  check "P3 kill -9: KeepAlive starts a new scheduler" waitfor 25 newpid "$lbl" "$pid"
  check "P3 kill -9: DAEMON-ALERT ... restarted on its own" waitfor 15 grep -q "^DAEMON-ALERT $lbl restarted on its own" "$fo"
  echo "  print, top level:"; top "$lbl"

  echo "-- 3. the guard's exit 0 stays down"
  cp "$cfg" "$cfg.orig"
  "$PY" -c 'import json, sys; p = sys.argv[1]; c = json.load(open(p)); c["owner"]["claude_config_dir"] += "-not-the-owner"; open(p, "w").write(json.dumps(c))' "$cfg"
  pid="$(lcf "$lbl" pid)"; echo "  owner changed in the config; kill -9 $pid"; kill -9 "$pid"
  sleep 20
  echo "  print, top level, 20 s later:"; top "$lbl"
  check "P3 guard: not running, no pid, last exit code 0" \
    eval "[ \"\$(lcf '$lbl' state)\" = 'not running' ] && [ -z \"\$(lcf '$lbl' pid)\" ] && [ \"\$(lcf '$lbl' 'last exit code')\" = 0 ]"
  check "P3 guard: the scheduler logged its owner refusal" grep -q 'not scheduling' "$slog"
  check "P3 guard: the follower reads it as a clean exit (inactive/dead, result=success) and names the guard" \
    waitfor 10 grep -q "^DAEMON-ALERT $lbl is not active (inactive/dead, result=success) - a clean exit is a GUARD refusal" "$fo"
  sleep 12
  check "P3 guard: still down 12 s later (exit 0 is not retried)" eval "[ -z \"\$(lcf '$lbl' pid)\" ]"
  cp "$cfg.orig" "$cfg"
  t "$LC" kickstart "gui/$U/$lbl"
  check "P3 guard: kickstart after the fix brings it back" waitfor 15 running "$lbl"
  check "P3 guard: DAEMON-OK ... is active again" waitfor 15 grep -q "^DAEMON-OK $lbl is active again" "$fo"
  sleep 3

  echo "-- 4. refresh --dry-run names where the config came from"
  out="$(t "$PY" "$F/systemd/agent-daemons.py" refresh --dry-run 2>&1)"; echo "$out" | show
  check "P3 dry-run: keeps the fresh job, config from the job definition (macOS cannot read a process's environment)" \
    eval "echo \"\$out\" | grep -q '^DRY-RUN keep $lbl: .*(config from job definition)'"

  echo "-- 5. the pinned script changes: refresh writes DAEMON-REFRESH and restarts the job"
  pid="$(lcf "$lbl" pid)"
  chmod u+w "$TT/canary/.claude/skills/scheduled-tasks/sched.py"
  echo "# changed by the macOS runbook" >> "$TT/canary/.claude/skills/scheduled-tasks/sched.py"
  out="$(t "$PY" "$F/systemd/agent-daemons.py" refresh --dry-run 2>&1)"; echo "$out" | show
  check "P3 refresh: the dry run would restart it for the changed script" \
    eval "echo \"\$out\" | grep -qF 'DRY-RUN restart $lbl: $TT/canary/.claude/skills/scheduled-tasks/sched.py changed after the process started'"
  out="$(t "$PY" "$F/systemd/agent-daemons.py" refresh 2>&1)"; echo "$out" | show
  check "P3 refresh: restarted with a new pid" waitfor 20 newpid "$lbl" "$pid"
  check "P3 refresh: the follower delivers DAEMON-REFRESH" waitfor 10 grep -qF "DAEMON-REFRESH restarting $lbl: $TT/canary/.claude/skills/scheduled-tasks/sched.py changed after the process started" "$fo"

  echo "-- 6. fleet pin-daemons $AG --clear"
  pid="$(lcf "$lbl" pid)"
  out="$(t fleet pin-daemons "$AG" --clear 2>&1)"; rc=$?; echo "$out" | show
  check "P3 clear: exit 0, re-rendered from the host checkout, restarted" \
    eval "[ $rc -eq 0 ] && echo \"\$out\" | grep -q '(unpinned)' && echo \"\$out\" | grep -q '^restarted $lbl'"
  check "P3 clear: no fleet-pin mark left" eval "! grep -q 'fleet-pin:' '$H/Library/LaunchAgents/$lbl.plist'"
  check "P3 clear: a new process" waitfor 15 newpid "$lbl" "$pid"
  sleep 2
  check "P3 clear: it runs the host checkout's sched.py again" \
    eval "ps -o command= -p \$(lcf '$lbl' pid) | grep -q -- '-u $F/.claude/skills/scheduled-tasks/sched.py\$'"

  echo "-- 7. kickstart of the refresh job writes its log"
  local before; before="$(lcf "$P.daemons-refresh" runs)"
  t "$LC" kickstart "gui/$U/$P.daemons-refresh"
  check "P3 refresh job: launchd ran it" waitfor 15 eval "[ \"\$(lcf '$P.daemons-refresh' runs)\" != '$before' ] && [ \"\$(lcf '$P.daemons-refresh' state)\" != running ]"
  echo "  print, top level:"; top "$P.daemons-refresh"
  check "P3 refresh job: its log exists" [ -f "$rlog" ]
  check "P3 refresh job: last exit code 0, not refresh's 3 for missing host settings (the plist's FLEET_HOST_CONFIG reached it)" \
    eval "[ \"\$(lcf '$P.daemons-refresh' 'last exit code')\" = 0 ]"
  ev "the refresh job's log ($(wc -c < "$rlog" 2>/dev/null | tr -d ' ') bytes):"
  show < "$rlog"
  echo "  note: launchd started it with the user's real HOME: it read this test's host.json through its plist's"
  echo "  FLEET_HOST_CONFIG and the real ~/Library/LaunchAgents, which hold none of this test's jobs, so it refreshed nothing"

  kill "$fpid" 2>/dev/null; wait "$fpid" 2>/dev/null
  echo "-- the follower's whole output"; show < "$fo"
  phase_end p3
}

r_p5() {
  local lbl="$P.session.$AG" envf="$A/$AG/secrets/personal/claude-auth.env" flog="$A/$AG/state/fake-claude.log"
  local slog="$A/$AG/state/session.log" out rc line dest plist want got boot pid
  mkdir -p "$H/fakebin"
  cat > "$H/fakebin/claude" <<'EOF'
#!/bin/bash
# A fake claude for the macOS runbook: logs how it was started, draws the ready
# status bar, then records every byte typed into the pane, raw.
log="${FAKE_CLAUDE_LOG:?}"
case " $* " in *" --update "*) echo "update $(date +%s)" >> "$log"; exit 0 ;; esac
echo "start $(date +%s) self=$0 token=${FAKE_TOKEN:-unset} config=${CLAUDE_CONFIG_DIR:-unset} nobytecode=${PYTHONDONTWRITEBYTECODE:-unset} path1=${PATH%%:*}" >> "$log"
exec /usr/bin/python3 -c 'import os, sys, time, tty
time.sleep(1)
sys.stdout.write("  >> bypass permissions on (shift+tab to cycle)\n"); sys.stdout.flush()
tty.setraw(0)
with open(sys.argv[1], "ab", buffering=0) as f:
    while True:
        b = os.read(0, 4096)
        if not b:
            break
        f.write(b)' "$log.keys"
EOF
  chmod 755 "$H/fakebin/claude"
  printf '# fleet-account: ada@example.com\nPATH=%s:$PATH\nFAKE_CLAUDE_LOG=%s\nFAKE_TOKEN=tok-example\n' "$H/fakebin" "$flog" > "$envf"
  chmod 600 "$envf"

  echo "-- adding-an-agent's agent-plist block, user form"
  skill_block agent-plist "a=$AG n='Ada Test' root='$A' fleet='$F' proj=work job=slack-watch var=SLACK_WATCH_CONFIG auth=token form=user" "$TT/agent-plist.sh" \
    || { fail "P5: no agent-plist block"; phase_end p5; }
  out="$(t /bin/bash "$TT/agent-plist.sh" 2>&1)"; rc=$?; echo "$out" | show
  plist="$A/$AG/config/$lbl.plist"; dest="$H/Library/LaunchAgents/$lbl.plist"
  want="install -m 644 $plist $dest && launchctl bootstrap gui/$U $dest"
  line="$(echo "$out" | tail -1)"
  check "P5 render: the block prints exactly the user form's command" [ "$line" = "$want" ]
  check "P5 render: the rendered plist lints" /usr/bin/plutil -lint "$plist"
  boot="$(plistval "$plist" 'd["ProgramArguments"][d["ProgramArguments"].index("--boot") + 1]')"
  ev "the boot message: ${#boot} characters"

  echo "-- before anything starts: the session's login shell must find the FAKE claude"
  got="$(env -i HOME="$REAL_HOME" USER="$ME" PATH="$(plistval "$plist" 'd["EnvironmentVariables"]["PATH"]')" /bin/bash -lc \
    "export PATH='$(plistval "$plist" 'd["EnvironmentVariables"]["PATH"]')':\"\$PATH\"; set -a; . '$envf'; set +a; command -v claude" 2>/dev/null)"
  ev "claude in the session's shell: $got"
  if [ "$got" != "$H/fakebin/claude" ]; then fail "P5: the session would not run the fake claude; nothing started"; phase_end p5; fi
  pass "P5: the session's shell resolves claude to the fake"

  [ "$line" = "$want" ] || phase_end p5
  t /bin/bash -c "$line"; rc=$?
  check "P5 start: the printed command ran (install, bootstrap)" [ "$rc" -eq 0 ]
  check "P5 start: the supervisor runs" waitfor 15 running "$lbl"
  echo "  waiting for the 60 s pre-sleep and the ready status bar"
  check "P5 boot: boot message sent" waitfor 150 grep -q "boot message sent to claude-$AG" "$slog"
  sleep 2
  count() { "$PY" -c 'import sys; print(open(sys.argv[1], "rb").read().count(sys.argv[2].encode() + b"\r"))' "$flog.keys" "$boot" 2>/dev/null || echo 0; }
  check "P5 boot: the fake received the boot message once, exactly, then Enter" [ "$(count)" = 1 ]
  check "P5 boot: the fake ran (not the real claude), with the job's config dir, no bytecode" \
    eval "grep -q 'self=$H/fakebin/claude .* config=$A/$AG/.claude nobytecode=1' '$flog'"
  check "P5 boot: claude --update went to the fake" grep -q '^update ' "$flog"
  out="$(t "$H/.local/bin/claude-attach" 2>&1)"; rc=$?; echo "$out" | show
  check "P5 claude-attach: the roster lists $AG (exit 2, the usage path)" eval "[ $rc -eq 2 ] && echo \"\$out\" | grep -qx '  $AG'"

  echo "-- the session is killed: the supervisor exits 1 and launchd starts a new one"
  t env TMUX_TMPDIR="$SOCKDIR" "$TMUX_BIN" kill-session -t "claude-$AG"
  check "P5 relaunch: the supervisor saw the session end" waitfor 15 grep -q "claude-$AG ended; exiting 1" "$slog"
  check "P5 relaunch: a new session, briefed again (a new session gets the boot message)" waitfor 150 eval "[ \"\$(grep -c 'boot message sent to claude-$AG' '$slog')\" = 2 ]"
  sleep 2
  check "P5 relaunch: the boot message reached the new session (two in all)" [ "$(count)" = 2 ]

  echo "-- kill -9 of the supervisor: the new one adopts the session and types nothing"
  pid="$(lcf "$lbl" pid)"; echo "  kill -9 $pid"; kill -9 "$pid"
  check "P5 adopt: launchd starts a new supervisor" waitfor 20 newpid "$lbl" "$pid"
  check "P5 adopt: it adopted the running session" waitfor 10 grep -q "adopted the running session claude-$AG" "$slog"
  sleep 8
  check "P5 adopt: no boot message retyped (still two)" [ "$(count)" = 2 ]
  check "P5 adopt: the session survived its supervisor's kill -9" t env TMUX_TMPDIR="$SOCKDIR" "$TMUX_BIN" has-session -t "=claude-$AG"

  echo "-- bootout: SIGTERM, the supervisor kills the session"
  t "$LC" bootout "gui/$U/$lbl"
  check "P5 bootout: launchd holds nothing of it" waitfor 35 notfound "$lbl"
  check "P5 bootout: the session is gone" waitfor 10 eval "! t env TMUX_TMPDIR='$SOCKDIR' '$TMUX_BIN' has-session -t '=claude-$AG' 2>/dev/null"
  check "P5 bootout: the supervisor logged the kill" grep -q "SIGTERM: killed session claude-$AG; exiting 0" "$slog"
  echo "-- session.log"; show < "$slog"
  echo "-- the fake's log"; show < "$flog"
  phase_end p5
}

r_p6() {
  local lbl="$P.stall-watchdog.$AG" staged="$A/$AG/config/stall-watchdog.json" state="$A/$AG/state/stall-watchdog"
  local skill="$F/.claude/skills/stall-watchdog" keys="$TT/wd-keys.log" out rc line want plist dest pid notice ver
  mkdir -p "$SOCKDIR"; chmod 700 "$SOCKDIR"
  cat > "$TT/pane.py" <<'EOF'
import os, sys, tty
sys.stdout.write(open(sys.argv[1], encoding="utf-8").read())
sys.stdout.flush()
tty.setraw(0)
with open(sys.argv[2], "ab", buffering=0) as log:
    while True:
        b = os.read(0, 1)
        if not b:
            break
        log.write(b)
EOF
  : > "$keys"
  echo "-- a pane on the agent's socket drawing a real captured confirmation prompt"
  t env TMUX_TMPDIR="$SOCKDIR" LC_ALL=en_US.UTF-8 "$TMUX_BIN" -u new-session -d -s "claude-$AG" -x 200 -y 50 \
    "$PY $TT/pane.py $skill/fixtures/real-prompt-a.txt $keys"
  check "P6: the pane shows the prompt" waitfor 10 eval "t env TMUX_TMPDIR='$SOCKDIR' '$TMUX_BIN' capture-pane -p -t 'claude-$AG:0' | grep -q 'Do you want to proceed?'"

  echo "-- adding-an-agent's watchdog-plist block, user form"
  skill_block watchdog-plist "a=$AG root='$A' fleet='$F' proj=work form=user" "$TT/watchdog-plist.sh" \
    || { fail "P6: no watchdog-plist block"; phase_end p6; }
  out="$(t /bin/bash "$TT/watchdog-plist.sh" 2>&1)"; rc=$?; echo "$out" | show
  plist="$A/$AG/config/$lbl.plist"; dest="$H/Library/LaunchAgents/$lbl.plist"
  want="install -m 644 $plist $dest && launchctl bootstrap gui/$U $dest"
  line="$(echo "$out" | tail -1)"
  check "P6 render: the block prints exactly the user form's command" [ "$line" = "$want" ]
  [ "$line" = "$want" ] || phase_end p6
  echo "  tuning the staged config for the test (SKILL.md step 5's edit): stall_secs 4, poll_secs 1"
  "$PY" -c 'import json, sys; p = sys.argv[1]; c = json.load(open(p)); c["stall"]["stall_secs"] = 4; c["stall"]["poll_secs"] = 1; open(p, "w").write(json.dumps(c, indent=2) + "\n")' "$staged"
  ver="$(sed -n 's/^version:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$skill/SKILL.md" | head -1)"
  mkdir -p "$W/.claude/skills/stall-watchdog/installation"
  "$PY" -c 'import json, socket, sys; c, v, out = sys.argv[1:]; json.dump({"hosts": {socket.gethostname(): {c: {"version": int(v)}}}}, open(out, "w"))' \
    "$staged" "$ver" "$W/.claude/skills/stall-watchdog/installation/.install-state.json"
  t /bin/bash -c "$line"; rc=$?
  check "P6 start: the printed command ran" [ "$rc" -eq 0 ]
  check "P6 start: the watchdog runs" waitfor 15 running "$lbl"

  notice="$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["action"]["notice"][:40])' "$staged")"
  check "P6 refuses: the prompt pane received Escape, then the notice" waitfor 30 eval \
    "\"$PY\" -c 'import sys; k = open(sys.argv[1], \"rb\").read(); n = sys.argv[2].encode(); sys.exit(0 if k.startswith(b\"\\x1b\") and n in k else 1)' '$keys' \"\$notice\""

  echo "-- kill -9: KeepAlive"
  pid="$(lcf "$lbl" pid)"; echo "  kill -9 $pid"; kill -9 "$pid"
  check "P6 respawn: a new watchdog process" waitfor 25 newpid "$lbl" "$pid"
  check "P6 respawn: it runs as $ME" eval "[ \"\$(ps -o user= -p \$(lcf '$lbl' pid) | tr -d ' ')\" = '$ME' ]"

  echo "-- touch watchdog.py: it re-executes itself"
  sleep 3
  pid="$(lcf "$lbl" pid)"
  local ups; ups="$(grep -c 'watchdog up' "$state/watchdog.log")"
  touch "$skill/watchdog.py"
  check "P6 re-exec: the log says it re-executes" waitfor 15 grep -q 'changed on disk - re-executing' "$state/watchdog.log"
  check "P6 re-exec: a new 'watchdog up' on the same pid" waitfor 10 eval \
    "[ \"\$(grep -c 'watchdog up' '$state/watchdog.log')\" -gt $ups ] && [ \"\$(lcf '$lbl' pid)\" = '$pid' ]"

  echo "-- installation/check: a LaunchAgent watchdog is UNPROTECTED"
  sleep 2
  out="$(t env FLEET_CONTEXT_ROOT="$W" "$PY" "$skill/installation/check" "$staged" 2>&1)"; rc=$?; echo "$out" | show
  check "P6 check: exit 1, UNPROTECTED" eval "[ $rc -eq 1 ] && echo \"\$out\" | tail -1 | grep -q '^UNPROTECTED: $lbl runs as a LaunchAgent in gui/$U'"

  t "$LC" bootout "gui/$U/$lbl"
  check "P6: bootout unloads the watchdog" waitfor 15 notfound "$lbl"
  t env TMUX_TMPDIR="$SOCKDIR" "$TMUX_BIN" kill-server 2>/dev/null
  echo "-- watchdog.log"; show < "$state/watchdog.log"
  phase_end p6
}

r_p7() {
  local cfg="$TT/agent-revive-config.json" tri="$F/.claude/skills/agent-revive/tmux_triage.sh"
  local fx="$F/.claude/skills/agent-revive/fixtures" out rc f st live boot
  "$PY" - "$F" "$A" "$P" "$cfg" <<'EOF'
import json, sys
f, a, p, out = sys.argv[1:]
ex = json.load(open(f + "/.claude/skills/agent-revive/config.example.json"))
c = json.load(open(f + "/.claude/skills/agent-revive/fixtures/config.fixture.json"))
c["fleet"].update(agents_home=a, systemd_unit=p + ".session.<agent>",
                  tmux={"tmpdir": a + "/run/claude-tmux-<agent>", "target": "claude-<agent>:0"},
                  daemons=[d for d in ex["fleet"]["daemons"] if "pattern" in d])
pool = f + "/.claude/skills/agent-health/fixtures/pool/"
c["accounts"].update(pool_file=pool + "pool.json", lease_file=pool + "leases.json", ledger_file=pool + "ledger.md")
open(out, "w").write(json.dumps(c, indent=2) + "\n")
EOF
  echo "-- --bootstrap-prompt, from the session plist (left by p5)"
  boot="$(plistval "$H/Library/LaunchAgents/$P.session.$AG.plist" 'd["ProgramArguments"][d["ProgramArguments"].index("--boot") + 1]')"
  out="$(t bash "$tri" "$AG" --config "$cfg" --bootstrap-prompt 2>&1)"; rc=$?
  check "P7 bootstrap-prompt: exit 0, the plist's --boot argument" eval "[ $rc -eq 0 ] && [ \"\$out\" = \"\$boot\" ]"
  out="$(t bash "$tri" "$AG" --config "$cfg" --facts 2>&1)"; rc=$?; echo "$out" | show
  check "P7 facts: launchd, the user scope, token auth, the plist's tmux directory" \
    eval "echo \"\$out\" | '$PY' -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if (d.get(\"unit_manager\"), d.get(\"unit_scope\"), d.get(\"auth\")) == (\"launchd\", \"user\", \"token\") and d.get(\"tmux_tmpdir\", d.get(\"tmpdir\")) == \"$SOCKDIR\" else 1)'"

  echo "-- stub panes, offline (--pane-file)"
  for f in healthy-pane usage-cap login-expired theme-prompt signin-url token-invalid; do
    st="$(t bash "$tri" "$AG" --config "$cfg" --pane-file "$fx/$f.txt" 2>/dev/null | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>&1)"
    ev "triage --pane-file $f.txt: state $st"
  done
  echo "-- the same panes LIVE, on the agent's socket: the live state equals the offline one"
  mkdir -p "$SOCKDIR"; chmod 700 "$SOCKDIR"
  for f in healthy-pane usage-cap; do
    st="$(t bash "$tri" "$AG" --config "$cfg" --pane-file "$fx/$f.txt" 2>/dev/null | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["state"])')"
    t env TMUX_TMPDIR="$SOCKDIR" "$TMUX_BIN" new-session -d -s "claude-$AG" -x 200 -y 50 "cat '$fx/$f.txt'; exec sleep 600"
    sleep 2
    out="$(t bash "$tri" "$AG" --config "$cfg" 2>&1)"
    live="$(echo "$out" | "$PY" -c 'import json, sys; d = json.load(sys.stdin); print(d["state"], d.get("daemons"), d.get("daemons_running"))' 2>&1)"
    ev "triage live $f: $live"
    check "P7 live $f: state $st, as offline" [ "${live%% *}" = "$st" ]
    t env TMUX_TMPDIR="$SOCKDIR" "$TMUX_BIN" kill-server 2>/dev/null
  done
  check "P7 live: the scheduler reads as running from agent-daemons.py status (macOS has no /proc)" \
    eval "echo \"\$live\" | grep -q \"'scheduler': True\""

  echo "-- redaction.test.mjs"
  out="$(cd "$F/.claude/skills/agent-revive/signin_driver" && t node redaction.test.mjs 2>&1)"; rc=$?
  echo "$out" | tail -3 | show
  check "P7 redaction.test.mjs: exit 0" [ "$rc" -eq 0 ]
  echo "-- share on macOS"
  out="$(t node "$F/.claude/skills/agent-revive/signin_driver/signin.mjs" "$AG" share --config "$cfg" --run-dir "$TT/share-run" 2>&1)"; rc=$?
  echo "$out" | show
  check "P7 share: refused, exit 2, not on macOS, naming step 7e" \
    eval "[ $rc -eq 2 ] && echo \"\$out\" | grep -q 'not on macOS' && echo \"\$out\" | grep -q 'step 7e'"
  phase_end p7
}

r_facts_b() {
  local f out
  echo "-- plutil -lint of every plist the phases rendered"
  for f in "$H"/Library/LaunchAgents/*.plist "$A/$AG"/config/*.plist; do
    [ -f "$f" ] || continue
    out="$(/usr/bin/plutil -lint "$f" 2>&1)"
    ev "plutil -lint ${f#$R/}: $(echo "$out" | sed "s|$R/||")"
  done
  echo "-- the BSD forms the install's printed commands use"
  ev "install with no arguments (BSD usage): $(install 2>&1 | tr '\n' ' ')"
  mkdir -p "$TT/bsd"
  install -d -m 755 "$TT/bsd/d" && install -m 644 /dev/null "$TT/bsd/f"
  ev "install -d -m 755 -> $(stat -f %Lp "$TT/bsd/d"); install -m 644 -> $(stat -f %Lp "$TT/bsd/f")"
  ev "stat -f \"%Sm %N\" -t \"%F %T\" on the cursors: $(stat -f "%Sm %N" -t "%F %T" "$A/$AG"/state/daemons/*.log.cursor 2>&1 | sed "s|$R/||" | tr '\n' ';')"
  ev "grep \"started claude-\" session.log | tail -1: $(grep "started claude-" "$A/$AG/state/session.log" | tail -1)"
  ev "launchctl print ... | grep -E \"^[[:space:]](state|pid) =\": $(lcp "$P.sched.$AG" | grep -E "^[[:space:]](state|pid) =" | tr '\n' ';')"
  ev "command grep -cxE (the watchdog unit's guard form): $(printf 'a=1\nb=2\n' | command grep -cxE '(a|b)=[12]')"
  echo "-- read-only account facts"
  out="$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>&1)"
  ev "automatic login: $([ "$out" = "$ME" ] && echo "on, for the ssh user" || echo "'$out'")"
  ev "fdesetup status: $(fdesetup status 2>&1)"
  ev "dseditgroup -o checkmember com.apple.access_ssh: $(dseditgroup -o checkmember -m "$ME" com.apple.access_ssh 2>&1 | sed "s/$ME/<the ssh user>/g")"
  echo "-- bootstrap-target.sh --check under macOS's /bin/sh (read only; what --install, under sudo, would do)"
  local rc
  out="$(t sh "$F/.claude/skills/install-agent-fleet/bootstrap-target.sh" --check 2>&1)"; rc=$?
  echo "$out" | sed "s/$ME/<the ssh user>/g" | show
  check "facts-b: bootstrap-target.sh --check gives a verdict (exit 0, 1 or 3; got $rc)" eval "[ $rc -le 1 ] || [ $rc -eq 3 ]"
  out="$(t sh "$F/.claude/skills/install-agent-fleet/bootstrap-target.sh" --check --agents-user "$AG" \
    --agents-root "$TT/agents-root-check" --checkout "$TT/checkout-check" 2>&1)"; rc=$?
  echo "$out" | sed "s/$ME/<the ssh user>/g" | show
  check "facts-b: bootstrap-target.sh --check --agents-user gives a verdict (exit 0, 1 or 3; got $rc)" eval "[ $rc -le 1 ] || [ $rc -eq 3 ]"
  phase_end facts-b
}

r_status() {
  local l
  for l in $(/bin/launchctl list | awk -v p="$P." 'index($3, p) == 1 {print $3}'); do
    echo "$l state='$(lcf "$l" state)' pid='$(lcf "$l" pid)' runs='$(lcf "$l" runs)' last exit code='$(lcf "$l" "last exit code")'"
  done
  echo "processes naming agent-fleet-test:"; pgrep -fl agent-fleet-test
  exit 0
}

r_cleanup() {
  local labels l p pids="" d rest
  if [ ! -e "$R" ]; then echo "nothing to clean: $R does not exist"; phase_end cleanup; fi
  echo "-- the launchctl wrapper's log: counts, then every call that was not a print"
  if [ -f "$RB/launchctl.log" ]; then
    ev "calls run: $(grep -c ' RUN ' "$RB/launchctl.log"), refused: $(grep -c ' REFUSED ' "$RB/launchctl.log")"
    grep -E ' (RUN|REFUSED) ' "$RB/launchctl.log" | grep -vE ' RUN print ' | sed "s|$R/||g" | show
  fi
  echo "-- bootout every test label"
  labels="$(/bin/launchctl list | awk -v p="$P." 'index($3, p) == 1 {print $3}')"
  for l in $labels; do
    p="$(lcf "$l" pid)"
    [ -n "$p" ] && pids="$pids $p"
    echo "  bootout gui/$U/$l (pid ${p:-none})"
    "$LC" bootout "gui/$U/$l"
  done
  check "cleanup: no test label left in launchctl list" waitfor 40 eval "[ \$(/bin/launchctl list | grep -c agent-fleet-test) = 0 ]"
  echo "-- the test tmux servers"
  for d in "$A"/run/claude-tmux-*; do
    [ -d "$d" ] || continue
    echo "  kill-server on $d"
    env -u TMUX TMUX_TMPDIR="$d" "$TMUX_BIN" kill-server 2>/dev/null
  done
  for p in $pids; do
    if kill -0 "$p" 2>/dev/null; then echo "  pid $p outlived its job: kill -9 $p"; kill -9 "$p"; fi
  done
  sleep 1
  rest="$(pgrep -f agent-fleet-test)"
  for p in $rest; do
    echo "  left running, naming the test root: $(ps -o pid=,command= -p "$p" | sed "s|$R|<test root>|g"): kill $p"
    kill "$p" 2>/dev/null
  done
  [ -z "$rest" ] || sleep 2
  check "cleanup: no process names agent-fleet-test" [ -z "$(pgrep -f agent-fleet-test)" ]
  echo "-- what p1's tests left in /private/tmp: an empty directory is removed, anything else is reported"
  if [ -s "$RB/p1-tmp-left" ]; then
    while IFS= read -r d; do
      case "$d" in /private/tmp/?*) ;; *) echo "  not under /private/tmp, left alone: $d"; continue ;; esac
      if [ -d "$d" ] && [ ! -L "$d" ] && [ -z "$(ls -A "$d" 2>/dev/null)" ] && rmdir "$d"; then echo "  removed the empty directory $d"
      else echo "  LEFT, not an empty directory (report it): $(ls -ld "$d" 2>&1)"; fi
    done < "$RB/p1-tmp-left"
  fi
  echo "-- remove the test root (the install made the checkout read-only: u+w first)"
  chmod -R u+w ~/agent-fleet-test
  rm -rf ~/agent-fleet-test
  check "cleanup: ~/agent-fleet-test is gone" [ ! -e "$R" ]
  phase_end cleanup
}

remote_main() {
  remote_env
  local phase="${1:-}"; shift || true
  case "$phase" in
    preflight) r_preflight "$@" </dev/null ;;
    baseline) r_baseline </dev/null ;;
    verify) r_verify </dev/null ;;
    cleanup) r_cleanup </dev/null ;;
    status) r_status </dev/null ;;
    setup) r_setup "$@" </dev/null ;;
    p0) r_p0 </dev/null ;;
    facts-a) r_facts_a </dev/null ;;
    p1) r_p1 </dev/null ;;
    p2) r_p2 </dev/null ;;
    p3) r_p3 </dev/null ;;
    p5) r_p5 </dev/null ;;
    p6) r_p6 </dev/null ;;
    p7) r_p7 </dev/null ;;
    facts-b) r_facts_b </dev/null ;;
    *) die "unknown remote phase: $phase" ;;
  esac
}

# =========================================================================
# LOCAL HALF: runs on the control host
# =========================================================================

ssh_() {  # ssh_ [-n] <remote command>: the options go before the destination
  local n=""
  if [ "${1:-}" = -n ]; then n=-n; shift; fi
  ssh $n ${MACOS_SSH_KEY:+-i "$MACOS_SSH_KEY"} -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30 \
    "$MACOS_HOST" "$@"
}
rfile() { ssh_ -n "/bin/bash ~/agent-fleet-test/runbook/macos-host.sh --remote $*"; }   # the copy pushed there
rstdin() { ssh_ "/bin/bash -s -- --remote $1" < "$SELF"; }                            # this file, on stdin
# The preflight, with the busy pattern quoted for the remote login shell.
rpreflight() { ssh_ "/bin/bash -s -- --remote preflight $(printf '%q' "$BUSY_PATTERN")" < "$SELF"; }

wait_idle() {  # wait_idle <phase>: 0 idle; 75 still busy after MACOS_BUSY_WAIT; 1 preflight could not run
  local waited=0 max="${MACOS_BUSY_WAIT:-1800}" out rc
  while :; do
    out="$(rpreflight 2>&1)"; rc=$?
    case "$rc" in
      0) echo "preflight before $1: idle"; return 0 ;;
      75) ;;
      *) echo "preflight before $1 could not run (exit $rc): $out"; return 1 ;;
    esac
    if [ "$waited" -ge "$max" ]; then
      echo "preflight before $1: still busy after ${waited} s; nothing of $1 ran:"; echo "$out" | sed 's/^/  /'
      return 75
    fi
    echo "preflight before $1: busy, waiting (${waited}/${max} s):"; echo "$out" | sed 's/^/  /'
    sleep 30; waited=$((waited + 30))
  done
}

l_push() {
  local repo ref sha
  repo="$(git -C "$(dirname "$SELF")" rev-parse --show-toplevel)" || return 1
  ref="${MACOS_FLEET_REF:-HEAD}"
  if [ "$ref" != HEAD ] && ! git -C "$repo" show-ref -q "$ref"; then
    echo "push: MACOS_FLEET_REF=$ref is not a ref name (a branch or a tag; a bundle carries refs, not bare commits)"
    return 2
  fi
  sha="$(git -C "$repo" rev-parse --verify "$ref^{commit}")" || return 1
  git -C "$repo" bundle create "$EV/fleet.bundle" "$ref" --tags >/dev/null 2>&1 \
    || { echo "push: git bundle create $ref --tags failed"; return 1; }
  echo "push: $ref = $sha, $(wc -c < "$EV/fleet.bundle" | tr -d ' ') bytes, heads: $(git -C "$repo" bundle list-heads "$EV/fleet.bundle" | awk '{print $2}' | tr '\n' ' ')"
  ssh_ 'test ! -e ~/agent-fleet-test && mkdir -m 700 ~/agent-fleet-test ~/agent-fleet-test/tmp ~/agent-fleet-test/runbook' \
    || { echo "push: ~/agent-fleet-test exists there or cannot be created; nothing copied"; return 1; }
  ssh_ 'cat > ~/agent-fleet-test/tmp/fleet.bundle' < "$EV/fleet.bundle" || return 1
  ssh_ 'cat > ~/agent-fleet-test/runbook/macos-host.sh' < "$SELF" || return 1
  rfile setup "$sha"
}

l_compare() {  # l_compare <baseline log> <verify log>: every section but df
  local s diffs=0
  for s in list_count print_disabled launchagents launchdaemons runners residue tmp_mine user_tmp tmux test_root pgrep_test; do
    awk -v s="== $s" '$0 == s {on = 1; next} /^== / {on = 0} on' "$1" > "$EV/.b.$s"
    awk -v s="== $s" '$0 == s {on = 1; next} /^== / {on = 0} on' "$2" > "$EV/.v.$s"
    if cmp -s "$EV/.b.$s" "$EV/.v.$s"; then
      echo "COMPARE $s: same as the baseline"
    else
      echo "COMPARE $s: DIFFERS from the baseline"; diff "$EV/.b.$s" "$EV/.v.$s" | sed 's/^/  /'
      diffs=$((diffs + 1))
    fi
  done
  rm -f "$EV"/.b.* "$EV"/.v.*
  [ "$diffs" -eq 0 ] && echo "COMPARE: the machine matches its baseline in every section" \
    || echo "COMPARE: $diffs section(s) differ (above); each needs an explanation"
}

local_main() {
  [ -n "${MACOS_HOST:-}" ] || die "set MACOS_HOST=<user>@<host> (the Mac's ssh destination)"
  [ $# -ge 1 ] || die "give one or more phases (see the header of $0)"
  local ph rc
  for ph in "$@"; do
    case "$ph" in
      baseline|push|p0|facts-a|p1|p2|p3|p5|p6|p7|facts-b|cleanup|verify|status) ;;
      p6b) die "p6b installs a LaunchDaemon with sudo: it runs by hand, on the machine owner's go" ;;
      *) die "unknown phase: $ph" ;;
    esac
  done
  BUSY_PATTERN="${MACOS_BUSY_PATTERN:-Runner.Worker}"
  EV="${MACOS_EVIDENCE:-/tmp/fleet-macos-host-evidence}"
  mkdir -p "$EV" || die "cannot create $EV"
  for ph in "$@"; do
    echo "== $ph  $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$EV/$ph.log"
    wait_idle "$ph" 2>&1 | tee -a "$EV/$ph.log"
    rc=${PIPESTATUS[0]}
    [ "$rc" -eq 0 ] || exit "$rc"
    case "$ph" in
      baseline|verify|cleanup) rstdin "$ph" ;;
      push) l_push ;;
      *) rfile "$ph" ;;
    esac 2>&1 | tee -a "$EV/$ph.log"
    rc=${PIPESTATUS[0]}
    out="$(rpreflight 2>&1)"
    case $? in
      0) echo "preflight after $ph: idle" ;;
      *) echo "preflight after $ph: a job started during the phase:"; echo "$out" | sed 's/^/  /' ;;
    esac | tee -a "$EV/$ph.log"
    if [ "$ph" = verify ] && [ -f "$EV/baseline.log" ]; then
      l_compare "$EV/baseline.log" "$EV/verify.log" | tee -a "$EV/verify.log"
    fi
    echo "== $ph exit $rc  $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$EV/$ph.log"
    [ "$rc" -eq 0 ] && continue
    case "$ph:$rc" in
      baseline:*|push:*|p0:*|cleanup:*|*:2|*:3|*:255) ;;
      *:1) if [ -n "${MACOS_KEEP_GOING:-}" ]; then
             echo "macos-host: phase $ph failed; MACOS_KEEP_GOING is set, so the next phase runs"
             failed="${failed:-} $ph"; continue
           fi ;;
    esac
    echo "macos-host: phase $ph failed (exit $rc); stopping. Evidence: $EV"
    exit 1
  done
  [ -z "${failed:-}" ] || { echo "macos-host: failed phase(s):$failed. Evidence: $EV"; exit 1; }
  echo "macos-host: every phase passed. Evidence: $EV"
}

if [ "${1:-}" = "--remote" ]; then
  shift
  remote_main "$@"
else
  SELF="$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")"
  local_main "$@"
fi
