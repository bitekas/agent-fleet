#!/usr/bin/env bash
# Offline test for bin/claude-attach. No tmux server, no /run read: the socket trees
# are temp directories injected through XDG_RUNTIME_DIR and CLAUDE_ATTACH_RUN_DIR
# (Linux) and through the host settings' agents_root (macOS), the sockets are real
# unix sockets bound by python3, `tmux` is a stand-in first on PATH that records how
# it was called, and `uname` is a stand-in that says which system to be. So both
# platforms' cases run on either system, and the same assertions hold on both.
#
# WHAT EACH CASE IS FOR
#   - The roster lists an agent whose socket is LIVE and leaves out one whose directory
#     is there with no socket: a stopped agent is not attachable, and a sweep that
#     typed into it would read nothing. The CONTROL is that the dead agent's directory
#     really exists, so its absence from the list is the socket test deciding.
#   - On Linux the roster reads BOTH runtime directories, the user manager's
#     ($XDG_RUNTIME_DIR, where a user unit's %t puts the socket) and the system's
#     (/run): an agent in either is listed and attachable. Reading only /run lists
#     every user-unit agent as stopped. An agent live in both is listed once, and the
#     attach takes the user directory first.
#   - On macOS the roster reads <agents_root>/run, where the session supervisor puts
#     the socket, with agents_root from the host settings; unreadable host settings
#     are exit 2 naming the file.
#   - No argument is exit 2 (the roster's normal path); an unknown agent is exit 2 and
#     names every directory it looked in.
#   - The attach drops $TMUX and sets TMUX_TMPDIR: inside a tmux session $TMUX wins
#     over $TMUX_TMPDIR and the attach lands in the session you are sitting in. The
#     stand-in records both, with $TMUX set in the caller, so the case can fail.
# Exit: 0 pass, 1 a check failed.
set -u
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CA="$HERE/claude-attach"
# A short base: a unix socket path is limited to 104 bytes on macOS (108 on Linux),
# and macOS's TMPDIR alone is about 50.
TMP="$(mktemp -d /tmp/fca.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass+1)); else echo "FAIL - $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
sock() { mkdir -p "$(dirname "$1")"; python3 -c 'import socket, sys; s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' "$1"; }

uid="$(id -u)"
mkdir -p "$TMP/run/claude-tmux-grace/tmux-$uid" "$TMP/bin/linux" "$TMP/bin/darwin"
sock "$TMP/run/claude-tmux-ada/tmux-$uid/default"
sock "$TMP/user/claude-tmux-alan/tmux-$uid/default"
sock "$TMP/user/claude-tmux-ada/tmux-$uid/default"
sock "$TMP/agents/run/claude-tmux-mac/tmux-$uid/default"
mkdir -p "$TMP/agents/run/claude-tmux-gone/tmux-$uid"
printf '{"schema": 1, "agents_root": "%s/agents", "fleet_checkout": "/tmp/x", "claims_dir": "/tmp/y"}\n' "$TMP" > "$TMP/host.json"
printf '#!/usr/bin/env bash\nprintf "args=%%s\\n" "$*" > "%s"\nprintf "tmux_env=%%s\\n" "${TMUX-unset}" >> "%s"\nprintf "tmpdir=%%s\\n" "${TMUX_TMPDIR-unset}" >> "%s"\n' \
  "$TMP/tmux.log" "$TMP/tmux.log" "$TMP/tmux.log" > "$TMP/bin/tmux"
printf '#!/bin/sh\necho Linux\n' > "$TMP/bin/linux/uname"
printf '#!/bin/sh\necho Darwin\n' > "$TMP/bin/darwin/uname"
chmod +x "$TMP/bin/tmux" "$TMP/bin/linux/uname" "$TMP/bin/darwin/uname"
LINUX=(env XDG_RUNTIME_DIR="$TMP/user" CLAUDE_ATTACH_RUN_DIR="$TMP/run" PATH="$TMP/bin/linux:$TMP/bin:$PATH")
DARWIN=(env FLEET_HOST_CONFIG="$TMP/host.json" PATH="$TMP/bin/darwin:$TMP/bin:$PATH")

ok "control: ada's socket is a live socket, grace's directory exists without one" \
   "$([ -S "$TMP/run/claude-tmux-ada/tmux-$uid/default" ] && [ -d "$TMP/run/claude-tmux-grace" ] && [ ! -e "$TMP/run/claude-tmux-grace/tmux-$uid/default" ] && echo yes || echo no)" yes
ok "control: the uname stand-ins answer" "$("${LINUX[@]}" uname -s)/$("${DARWIN[@]}" uname -s)" "Linux/Darwin"

# --- Linux ---
roster="$("${LINUX[@]}" bash "$CA" 2>&1 >/dev/null)"; rc=$?
ok "linux: no argument is the roster: exit 2" "$rc" 2
ok "linux: the roster lists the live agents of BOTH runtime directories, each once, user directory first" \
   "$(sed -n '/^agents with a live tmux socket:$/,$p' <<<"$roster" | sed 1d | tr '\n' '|')" "  ada|  alan|"
err="$("${LINUX[@]}" bash "$CA" grace 2>&1 >/dev/null)"; rc=$?
ok "linux: an agent with no live socket: exit 2, naming both directories it looked in" \
   "$rc:$(grep -c "no tmux server for 'grace' at $TMP/user/claude-tmux-grace or $TMP/run/claude-tmux-grace" <<<"$err" | tr -d ' ')" "2:1"
"${LINUX[@]}" bash "$CA" alan; rc=$?
ok "linux: a user-unit agent (socket under \$XDG_RUNTIME_DIR) is attachable" \
   "$rc:$(sed -n 's/^tmpdir=//p' "$TMP/tmux.log")" "0:$TMP/user/claude-tmux-alan"
"${LINUX[@]}" bash "$CA" ada; rc=$?
ok "linux: an agent live in both directories attaches through the user directory" \
   "$rc:$(sed -n 's/^tmpdir=//p' "$TMP/tmux.log")" "0:$TMP/user/claude-tmux-ada"
rm -rf "$TMP/user/claude-tmux-ada"
TMUX=/tmp/some-other-session,1,0 "${LINUX[@]}" bash "$CA" ada -r; rc=$?
ok "attach: exit 0 through the stand-in" "$rc" 0
ok "attach: the session is claude-<agent>, and extra arguments pass through" "$(sed -n 's/^args=//p' "$TMP/tmux.log")" "attach -t claude-ada -r"
ok "attach: \$TMUX is dropped even when the caller is inside a session" "$(sed -n 's/^tmux_env=//p' "$TMP/tmux.log")" unset
ok "attach: a system-unit agent's TMUX_TMPDIR is its socket directory under /run" "$(sed -n 's/^tmpdir=//p' "$TMP/tmux.log")" "$TMP/run/claude-tmux-ada"

# --- macOS ---
roster="$("${DARWIN[@]}" bash "$CA" 2>&1 >/dev/null)"; rc=$?
ok "macos: the roster reads <agents_root>/run and lists only the live agent" \
   "$rc:$(sed -n '/^agents with a live tmux socket:$/,$p' <<<"$roster" | sed 1d | tr '\n' '|')" "2:  mac|"
"${DARWIN[@]}" bash "$CA" mac; rc=$?
ok "macos: attach uses <agents_root>/run/claude-tmux-<agent>" "$rc:$(sed -n 's/^tmpdir=//p' "$TMP/tmux.log")" "0:$TMP/agents/run/claude-tmux-mac"
err="$(env FLEET_HOST_CONFIG="$TMP/absent.json" PATH="$TMP/bin/darwin:$TMP/bin:$PATH" bash "$CA" mac 2>&1 >/dev/null)"; rc=$?
ok "macos: unreadable host settings: exit 2 naming the file" \
   "$rc:$(grep -c "cannot read agents_root from the host settings $TMP/absent.json" <<<"$err" | tr -d ' ')" "2:1"

echo ""; echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
