#!/usr/bin/env bash
# launchd-daemon.smoke.sh - the stall watchdog's LaunchDaemon form on a REAL macOS
# launchd: it runs as the invoking user under a root-owned job, captures, survives a
# kill -9 (KeepAlive), refuses an unprivileged bootout, and installation/check reads
# it OK.
#
#   bash .claude/skills/stall-watchdog/installation/launchd-daemon.smoke.sh
#
# NOT a *.test.* file, so tests/run-all.sh never discovers it, ON PURPOSE: it
# installs a job into the system domain with sudo. Run it only on a Mac whose
# owner has said go; CI never runs it (the ci-macos runner is the repository
# owner's own machine, with no passwordless sudo). It refuses
# (exit 2) unless the host is macOS, `sudo -n true` succeeds, and its label is not
# in use; everything it creates - the job, the plist, a tmux server, a temp
# directory - is removed on exit, and the removal of the job is verified.
#
# The label is com.agent-fleet-test.stall-watchdog.smoke: the test prefix, so it
# can never be mistaken for, or remove, a real install's watchdog.
#
# Exit codes: 0 every property held; 1 a property failed; 2 refused (not macOS, no
# passwordless sudo, label in use); 3 NO VERDICT (a setup step failed before the job
# under test was running, so nothing here says anything about it).
#
# Portable bash: macOS's /bin/bash 3.2 and BSD userland.
set -u
LABEL=com.agent-fleet-test.stall-watchdog.smoke
PLIST=/Library/LaunchDaemons/com.agent-fleet-test.stall-watchdog.smoke.plist
HERE="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(cd "$HERE/../../../.." && pwd -P)"
fails=0
ok() { echo "ok   - $1"; }
bad() { echo "FAIL - $1"; fails=$((fails + 1)); }
noverdict() { echo "NO VERDICT: $1"; exit 3; }

[ "$(uname -s)" = Darwin ] || { echo "refused: macOS only (launchd)"; exit 2; }
sudo -n true 2>/dev/null || { echo "refused: needs passwordless sudo (it installs a LaunchDaemon)"; exit 2; }
if launchctl print "system/$LABEL" >/dev/null 2>&1 || [ -e "$PLIST" ]; then
  echo "refused: $LABEL is already loaded or $PLIST exists - not this run's to replace"
  exit 2
fi

T="$(mktemp -d /tmp/wds.XXXXXX)" || noverdict "no temp directory"
T="$(cd "$T" && pwd -P)"
cleanup() {
  sudo -n launchctl bootout "system/$LABEL" >/dev/null 2>&1
  sudo -n rm -f /Library/LaunchDaemons/com.agent-fleet-test.stall-watchdog.smoke.plist
  env -u TMUX TMUX_TMPDIR="$T/run" tmux kill-server >/dev/null 2>&1
  if launchctl print "system/$LABEL" >/dev/null 2>&1; then echo "CLEANUP FAILED: $LABEL is still loaded"; fi
  rm -rf "$T"
}
trap cleanup EXIT

PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || PY="$(command -v python3)"
[ -n "$PY" ] || noverdict "no python3"
me="$(id -un)"
cfg="$T/smoke/config/stall-watchdog.json"
mkdir -p "$T/smoke/config" "$T/state" "$T/run" "$T/install/.claude/skills/stall-watchdog/installation" \
  || noverdict "cannot create the layout under $T"
chmod 700 "$T/state"
cp "$REPO/tests/fixtures/install/.claude/fleet.json" "$T/install/.claude/fleet.json" || noverdict "no fixture manifest"
"$PY" - "$REPO" "$T" "$cfg" <<'EOF' || noverdict "cannot write the config and the install record"
import json, os, re, socket, sys
repo, t, cfg = sys.argv[1:]
skill = os.path.join(repo, ".claude", "skills", "stall-watchdog")
c = json.load(open(os.path.join(skill, "config.example.json")))
c["tmux"] = {"tmpdir": os.path.join(t, "run"), "target": "smoke:0"}
c["stall"]["poll_secs"] = 1
c["state"]["dir"] = os.path.join(t, "state")
c["owner"]["claude_config_dir"] = None
json.dump(c, open(cfg, "w"))
version = int(re.search(r"^version:\s*(\d+)", open(os.path.join(skill, "SKILL.md")).read(), re.M).group(1))
rec = os.path.join(t, "install", ".claude", "skills", "stall-watchdog", "installation", ".install-state.json")
json.dump({"hosts": {socket.gethostname(): {cfg: {"version": version}}}}, open(rec, "w"))
EOF
env -u TMUX TMUX_TMPDIR="$T/run" tmux new-session -d -s smoke "sleep 600" || noverdict "no tmux session to watch"

sed -e "s|<launchd-prefix>|com.agent-fleet-test|g" -e "s|<agent>|smoke|g" -e "s|<user>|$me|g" \
    -e "s|<checkout>|$T|g" -e "s|<fleet>|$REPO|g" -e "s|<agents-root>|$T|g" \
    -e "s|<state dir>|$T/state|g" -e "s|<tmux-dir>|$T/run|g" -e "s|/opt/homebrew/bin/python3|$PY|g" \
    "$HERE/agent-stall-watchdog.plist.example" > "$T/rendered.plist"
plutil -lint "$T/rendered.plist" >/dev/null || noverdict "the rendered plist does not lint"
sudo -n install -m 644 -o root -g wheel "$T/rendered.plist" "$PLIST" && sudo -n launchctl bootstrap system "$PLIST" \
  || noverdict "the LaunchDaemon did not install (the printed sudo line of SKILL.md step 6)"

pid_of() { launchctl print "system/$LABEL" 2>/dev/null | sed -n 's/^	pid = \([0-9][0-9]*\)$/\1/p' | head -1; }
wait_pid() {  # wait_pid NOT_THIS SECS: a running pid other than NOT_THIS, or nothing
  local n=0 p
  while [ "$n" -lt "$2" ]; do
    p="$(pid_of)"
    if [ -n "$p" ] && [ "$p" != "$1" ]; then echo "$p"; return 0; fi
    sleep 1; n=$((n + 1))
  done
  return 1
}
pid1="$(wait_pid none 30)" || noverdict "$LABEL never reached a running pid"
ok "the LaunchDaemon runs (pid $pid1)"

user="$(ps -o user= -p "$pid1" | tr -d ' ')"
[ "$user" = "$me" ] && ok "it runs as the invoking user ($me), not root" || bad "it runs as '$user', not $me"

n=0; while [ ! -f "$T/state/stall-watchdog.json" ] && [ "$n" -lt 20 ]; do sleep 1; n=$((n + 1)); done
[ -f "$T/state/stall-watchdog.json" ] && ok "it captures: the state file was written" || bad "no state file after 20 s: up and blind"

[ -w "$PLIST" ] && bad "$PLIST is writable by $me" || ok "the job definition is not writable by the user it runs as"
if launchctl bootout "system/$LABEL" >/dev/null 2>&1; then
  bad "an unprivileged bootout of system/$LABEL SUCCEEDED: the watched agent could switch its watchdog off"
else
  [ "$(pid_of)" = "$pid1" ] && ok "an unprivileged bootout is refused and the job keeps running" \
    || bad "the bootout was refused but the job is no longer on pid $pid1"
fi

kill -9 "$pid1" 2>/dev/null || bad "the user could not signal its own watchdog (pid $pid1)"
pid2="$(wait_pid "$pid1" 40)" && ok "after kill -9, KeepAlive started it again (pid $pid2)" \
  || bad "no new pid within 40 s of kill -9"

sleep 3   # the new process writes its first state after it starts (poll 1 s)
out="$(FLEET_CONTEXT_ROOT="$T/install" FLEET_SERVICE_BACKEND=launchd "$PY" "$HERE/check" "$cfg" 2>&1)"; rc=$?
last="$(printf '%s\n' "$out" | tail -1)"
case "$rc:$last" in
  "0:OK:"*"$LABEL"*) ok "installation/check reads the LaunchDaemon OK" ;;
  *) bad "installation/check: exit $rc, $last" ;;
esac

echo ""
[ "$fails" -eq 0 ] && { echo "LAUNCHD SMOKE PASSED"; exit 0; }
echo "LAUNCHD SMOKE FAILED: $fails property(ies)"
exit 1
