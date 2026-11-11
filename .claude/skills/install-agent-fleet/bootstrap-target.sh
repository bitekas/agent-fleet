#!/bin/sh
# bootstrap-target.sh - check, and on request install, what agent-fleet needs on
# the machine the agents will run on. It runs ON that machine, over SSH. POSIX
# sh; it needs nothing a fresh Ubuntu or macOS install lacks.
#
# Usage, from the local machine (<host> is <user>@<address>, the SSH destination
# the target guide ends with, and <user> is the administrator, the login with
# sudo - or, on a machine where it has none, the account the agents run as):
#
#   scp "${CLAUDE_SKILL_DIR}/bootstrap-target.sh" <host>:/tmp/bootstrap-target.sh
#   ssh <host> 'sh /tmp/bootstrap-target.sh --check [--with-node] [--with-browser] [--agents-user <name> [--agents-root <dir>] [--checkout <dir>]]'
#   scp <read-back file> <host>:<read-back file>
#   ssh <host> 'sudo -S -p "" sh /tmp/bootstrap-target.sh --install --read-back <read-back file> [same options] [--agents-password-file <file>]' < <password file>
#
# --read-back <file> (--install): install-agent-fleet's step-2 message, the
# one sent to the person, saved in a file on this machine. Its first line must
# be exactly `Read back before install` and the lines after it must list the
# answers (at least one line that is not blank). --install refuses a missing,
# empty or wrongly headed file (exit 2, nothing changed), naming the step-2
# message; it prints the file at the top of its output and keeps a copy in the
# agents' user's ~/.config/agent-fleet/read-back.txt, beside the host settings
# `fleet install` writes there. --check takes no read-back: it runs before the
# message, which reports what it found.
#
# --check runs as <user>, read only. --install runs under ONE `sudo -S`: sudo
# reads the password from the first line of stdin, and the script itself reads
# no stdin, takes no password argument and calls no sudo that could prompt
# again. On a machine whose sudo needs no password (a cloud image's default
# user) stdin may be empty.
#
# The agents' user is `--agents-user <name>` when given - the dedicated user
# without sudo that runs the agents, while <user> is the administrator who
# runs this script - and otherwise `SUDO_USER`, which sudo sets (an install
# whose login user has no sudo at all, where the agents run as that user).
# The agents' own parts - Claude Code, ~/.profile, lingering - are that
# user's, and run as that user, never as root. Homebrew and its formulas are
# the ADMINISTRATOR's (the HOMEBREW property below), never the agents user's.
#
# --agents-user:
#   agents-user  the user exists: --install runs, on Linux, `useradd
#                --create-home --shell /bin/bash --user-group <name>`, which
#                leaves its password locked and names no supplementary group;
#                on macOS `sysadminctl -addUser <name> -fullName <name> -shell
#                /bin/bash -home /Users/<name> -password <its password>`, a
#                STANDARD account (no -admin), then `createhomedir -c -u <name>`.
#                It is UNSUPPORTED when the user is in group sudo, admin or wheel.
#   agents-group (macOS) a group named <name>, which --install creates with
#                `dseditgroup -o create`: a macOS account's primary group is the
#                shared `staff`, so the agents root needs a group of its own for
#                the administrator to read it through.
#   agents-sudo  as root, `sudo -l -U <name>` says the user may run nothing
#                (its TEXT is read, never its exit status); UNSUPPORTED when it
#                lists a rule; `unknown` without root.
#   agents-root  --agents-root, else <its home>/agents, is a directory the user
#                owns, in its own group, mode 750: --install creates it, or sets
#                that group and mode on one the user owns; UNSUPPORTED when it
#                exists and someone else owns it.
#   admin-group  the administrator is in the agents user's group, so it reads the
#                agents root (fleet upgrade reads every install's manifest) and
#                writes nothing there: the root is 750. --install runs `usermod
#                -a -G <agents-user> <administrator>`, which takes effect at the
#                administrator's next login. It adds the ADMINISTRATOR to a group
#                and gives the agents user nothing. On macOS: `dseditgroup -o edit
#                -a <administrator> -t user <name>`.
#   agents-ssh   <its home>/.ssh/authorized_keys holds a key: --install copies
#                the invoking administrator's (SUDO_USER's, else root's), so the
#                person's key that reaches <user> reaches the agents' user too.
#                On macOS, where Remote Login is limited to the group
#                com.apple.access_ssh, the user is in it (ssh-access): --install
#                adds it with dseditgroup.
#   checkout-dir --checkout, else /opt/agent-fleet: the directory the
#                administrator clones the fleet checkout into, the administrator's
#                own, mode 755, OUTSIDE the agents root: --install creates it.
#                The agents user only reads the checkout; inside its agents root
#                it could rename the checkout away and put its own in its place.
#                UNSUPPORTED inside the agents root, or owned by anyone else.
#
# Automatic login (macOS; every form): the agents' launchd jobs run in the
# session of the account that logs in at boot, as lingering keeps them running
# on Linux, so the agents' user must be that account (autologin): --install
# runs `sysadminctl -autologin set -userName <user> -password <its password>`.
# FileVault on is UNSUPPORTED: macOS does not log in automatically while it is.
#
# --agents-password-file <file> (macOS, --install): the agents' user's account
# password, one line, in a file on this machine root can read - handed over the
# way every secret is (install-agent-fleet SKILL.md). Creating that account and
# its automatic login both need it, so --install refuses (exit 2, nothing done)
# when either is MISSING and no file is given. The password is never printed:
# each command that takes it is echoed with the password replaced, and it goes
# to root-run sysadminctl only, whose arguments no other user can read on macOS
# (the kernel serves a process's arguments to its own uid and root only). The
# script never removes the file.
# The script never removes a right and never changes an existing owner: an
# account that already has sudo, or a root someone else owns, is refused, and
# the person picks another name or fixes it by hand.
#
# Supported: Linux with apt (Debian, Ubuntu) whose own /usr/bin/python3 is 3.11
# or newer - Ubuntu 26.04 LTS is the tested one - and macOS on Apple Silicon.
#
# What it checks, and how --install provides each:
#   git, tmux, curl              apt; Homebrew
#   python3 3.11 or newer        Linux: /usr/bin/python3 from apt; macOS: Homebrew's python
#   node 22+ and npm             only with --with-node: apt nodejs npm; Homebrew node
#   browser packages             only with --with-browser (implies --with-node), Linux:
#                                the apt packages agent-revive names (jq xvfb x11vnc
#                                novnc websockify), then Playwright's chromium libraries
#                                (`npx playwright@<version> install-deps chromium`, every
#                                --install; PLAYWRIGHT_VERSION below)
#   lingering (Linux)            `loginctl enable-linger <user>`
#   automatic login (macOS)      `sysadminctl -autologin set`, with --agents-password-file
#   Homebrew (macOS)             its documented installer, unattended (NONINTERACTIVE=1), as
#                                the administrator, https://docs.brew.sh/Installation
#                                (checked 2026-11-06)
#   Claude Code                  the vendor's native installer, as <user>,
#                                https://code.claude.com/docs/en/setup (checked 2026-11-06)
#
# Modes:
#   --check    read only: no sudo that elevates, no network, no write. One line
#              per item - ok, MISSING, UNSUPPORTED, n/a, or unknown for what
#              only root can read (another user's sudo rules, Claude Code in
#              another user's home) - then a summary line. Run as root, it reads
#              those too, and `sudo -l -U` is its one sudo call.
#   --install  installs what the check finds MISSING, then checks again and
#              exits by THAT result: a 0 means the machine now has everything,
#              not that the installers exited 0.
#
# Exit codes: 0 nothing missing; 1 something missing (--check), or an install
# step failed (--install: the step named, nothing after it run); 2 usage,
# --install without a valid --read-back file (the line names the step-2
# message), or --install without the root it needs (the line names the
# invocation); 3 an UNSUPPORTED item, which --install cannot fix (the line says
# why).
#
# LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole:
#
#   * --install REFUSES WITHOUT THE READ-BACK FILE, BEFORE IT RUNS ANYTHING. The
#     skill's step 2 lists every answer back to the person in one message headed
#     `Read back before install`, their one chance to correct an answer before
#     anything is installed. Prose alone does not hold that gate: stranger runs
#     of the skill reached this install without sending it, one past the
#     heading itself. A FLAG did not hold it either: a flag is a word the
#     session is told, every printed invocation carried it, and a session
#     copied the command and passed the flag having sent nothing. So the gate is
#     an ARTIFACT the install consumes: the message itself, in a file whose
#     first line is the heading and which lists the answers, printed at the top
#     of the install's output and kept on the machine, so it stands in the
#     transcript and on the target. Every invocation this repository prints
#     shows `--read-back <read-back file>`, never a ready-made value, and there
#     is no flag form left to copy. The test asserts that each refusal (no
#     file, a missing, empty or wrongly headed one, one with no answers, the
#     retired flag) runs no command and writes nothing (the fake machine's call
#     log and snapshot), and that the same machine with a valid file installs,
#     so the "nothing" is measured by an instrument that sees an install.
#
#   * --check MAKES NO CHANGE AND RUNS NO SUDO THAT ELEVATES. The skill runs it
#     first and shows the list before the person agrees to anything; a check
#     with a side effect makes that consent meaningless. Its only sudo calls are
#     `sudo -u <agents' user>` from root, which drops privilege, and `sudo -l -U`
#     from root, which lists. The test records every command a check runs and
#     snapshots the machine, and asserts nothing installs or writes.
#
#   * --install ENDS WITH A SECOND CHECK AND EXITS BY IT. An installer can exit 0
#     and leave the thing absent (a PATH the login shell does not have, a package
#     with another binary name). Only the re-check is evidence.
#
#   * A TOOL COUNTS ONLY IF IT RUNS. On a Mac without the Command Line Tools,
#     /usr/bin/git and /usr/bin/python3 exist and are stubs that fail and open an
#     install dialog; a check by existence would report them ok. Each tool is
#     run, and those stubs are not run at all.
#
#   * NO DOWNLOAD IS PIPED INTO A SHELL. POSIX sh has no pipefail: in
#     `curl ... | bash` a failed download feeds bash nothing and the step exits
#     0, and `bash -c "$(curl ...)"` does the same. Every installer is
#     downloaded to a file first, so a failed download fails its step.
#
#   * /usr/bin/python3 IS THE PYTHON THAT COUNTS ON LINUX. The fleet's daemon
#     units run /usr/bin/python3, so a newer Python installed beside it does not
#     serve them; a distribution whose own python3 is older than 3.11 is
#     reported UNSUPPORTED rather than patched around. The floor is measured:
#     the fleet's tests fail on 3.10 (ast.TryStar, new in 3.11) and pass on 3.11
#     to 3.14.
#
#   * CLAUDE CODE IS FOUND THROUGH A LOGIN SHELL ON LINUX. The agent units start
#     it with `bash -l` under systemd's bare PATH; a `claude` that only the
#     current shell finds is reported MISSING (claude-path).
#
#   * HOMEBREW IS THE ADMINISTRATOR'S, NEVER THE AGENTS USER'S. Whoever owns
#     /opt/homebrew can replace every program in it, and the protected stall
#     watchdog runs Homebrew's python3 (agent-stall-watchdog.plist.example): an
#     agents user that owned it could swap the interpreter of the job meant to
#     supervise it. So Homebrew's installer and every `brew install` run as the
#     administrator - SUDO_USER, the account that ran this script through sudo
#     (<user> in the usage) - with or without --agents-user, and as root with
#     no SUDO_USER (no administrator to install as) --install refuses before it
#     changes anything. The agents user only runs what Homebrew installed.
#
#   * HOMEBREW'S INSTALLER GETS A SUDO GRANT THAT DIES WITH THE RUN. It refuses
#     to run as root and calls `sudo -n` itself, and the one password this run
#     had went to the outer `sudo -S`. So, as root, the script writes
#     /etc/sudoers.d/agent-fleet-bootstrap (the administrator NOPASSWD, checked
#     by visudo), runs the installer as the administrator, and deletes the file
#     right after it and on every exit path, signals included. The administrator
#     can run anything as root already; the grant only spares a second password.
#     A file left behind would be a standing passwordless root for that account,
#     and one naming the agents user would make it root; the test asserts the
#     grant names the administrator and is gone.
#
#   * ROOT'S BROWSER LIBRARIES COME FROM A PINNED PLAYWRIGHT. `npx --yes
#     playwright` with no version fetches whatever the registry serves as latest
#     and runs it as root. PLAYWRIGHT_VERSION is the version the sign-in
#     driver's package-lock.json pins (agent-revive/signin_driver), so the
#     libraries are the ones the driver's own browser needs and nothing newer
#     runs as root; the test reads the lockfile and fails when the two differ.
#
#   * THE AGENTS USER IS NEVER GIVEN SUDO, AND ITS SUDO IS READ, NOT ASSUMED.
#     The agents run Claude Code with every permission prompt off; a user with
#     sudo turns that into root. useradd gets no group option, and the re-check
#     reads `sudo -l -U` as root, so a site whose sudoers grants new users
#     something (an %users rule, a cloud agent's group) is refused at the end
#     instead of reported ok. The test asserts the useradd argv and that no
#     sudoers file or group change is written.

set -u

# A fake root for the files read and written below. Tests only; never set it on a real machine.
ROOT="${BOOTSTRAP_ROOT:-}"
CLAUDE_URL="https://claude.ai/install.sh"
BREW_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
BROWSER_PKGS="jq xvfb x11vnc novnc websockify"
# The sign-in driver's Playwright (its package-lock.json); bootstrap-target.test.py fails when they differ.
PLAYWRIGHT_VERSION="1.63.0"
SUDOERS="$ROOT/etc/sudoers.d/agent-fleet-bootstrap"

usage() {
  echo "usage: sh bootstrap-target.sh (--check | --install --read-back <read-back file>) [--with-node] [--with-browser] [--agents-user <name> [--agents-root <dir>] [--checkout <dir>]] [--agents-password-file <file>]" >&2
  exit "${1:-2}"
}

MODE="" READ_BACK="" WITH_NODE="" WITH_BROWSER="" AGENTS_USER="" AGENTS_ROOT="" CHECKOUT="" PWFILE=""
while [ $# -gt 0 ]; do
  case $1 in
    --check | --install) [ -z "$MODE" ] || usage; MODE=${1#--} ;;
    --read-back) [ $# -ge 2 ] || usage; READ_BACK=$2; shift ;;
    --with-node) WITH_NODE=1 ;;
    --with-browser) WITH_BROWSER=1; WITH_NODE=1 ;;
    --agents-user) [ $# -ge 2 ] || usage; AGENTS_USER=$2; shift ;;
    --agents-root) [ $# -ge 2 ] || usage; AGENTS_ROOT=$2; shift ;;
    --checkout) [ $# -ge 2 ] || usage; CHECKOUT=$2; shift ;;
    --agents-password-file) [ $# -ge 2 ] || usage; PWFILE=$2; shift ;;
    -h | --help) usage 0 ;;
    *) usage ;;
  esac
  shift
done
[ -n "$MODE" ] || usage
# --install only with the step-2 read-back in a file (LOAD-BEARING, the first property).
READ_BACK_HEAD="Read back before install"
read_back_refused() {
  echo "REFUSED: $1; nothing was changed. Step 2 of install-agent-fleet comes first: send the person the message whose first line is '$READ_BACK_HEAD', listing every answer back, save the same text in a file on this machine, and run --install --read-back <read-back file>." >&2
  exit 2
}
if [ "$MODE" = install ]; then
  [ -n "$READ_BACK" ] || read_back_refused "--install without --read-back <read-back file>"
  [ -f "$READ_BACK" ] && [ -r "$READ_BACK" ] || read_back_refused "--read-back $READ_BACK: no readable file there"
  [ -s "$READ_BACK" ] || read_back_refused "--read-back $READ_BACK is empty"
  [ "$(sed -n 1p "$READ_BACK")" = "$READ_BACK_HEAD" ] \
    || read_back_refused "the first line of --read-back $READ_BACK is not exactly '$READ_BACK_HEAD'"
  [ -n "$(sed -n '2,$p' "$READ_BACK" | tr -d ' \t\r\n')" ] \
    || read_back_refused "--read-back $READ_BACK lists no answers after its first line"
  echo "== read-back ($READ_BACK):"
  cat "$READ_BACK"
  echo "== end of the read-back"
fi
# The names below reach useradd, sudo and a path, so only the safe forms pass:
# Debian's user-name rule (lowercase, at most 32), and an absolute path of
# characters that need no quoting.
if [ -n "$AGENTS_USER" ]; then
  case $AGENTS_USER in
    root | [!a-z_]* | *[!a-z0-9_-]*) echo "REFUSED: --agents-user '$AGENTS_USER': a lowercase name, not root" >&2; exit 2 ;;
  esac
  [ ${#AGENTS_USER} -le 32 ] || { echo "REFUSED: --agents-user is longer than 32 characters" >&2; exit 2; }
fi
if [ -n "$AGENTS_ROOT" ]; then
  [ -n "$AGENTS_USER" ] || { echo "REFUSED: --agents-root needs --agents-user" >&2; exit 2; }
  case $AGENTS_ROOT in
    / | [!/]* | *[!A-Za-z0-9._/@+-]*) echo "REFUSED: --agents-root '$AGENTS_ROOT': an absolute path of A-Z a-z 0-9 . _ / @ + -" >&2; exit 2 ;;
  esac
fi
if [ -n "$CHECKOUT" ]; then
  [ -n "$AGENTS_USER" ] || { echo "REFUSED: --checkout needs --agents-user" >&2; exit 2; }
  case $CHECKOUT in
    / | [!/]* | *[!A-Za-z0-9._/@+-]*) echo "REFUSED: --checkout '$CHECKOUT': an absolute path of A-Z a-z 0-9 . _ / @ + -" >&2; exit 2 ;;
  esac
fi

IS_ROOT=""
[ "$(id -u)" -eq 0 ] && IS_ROOT=1
WHO=$(id -un)
if [ -n "$AGENTS_USER" ]; then ME=$AGENTS_USER
elif [ -n "$IS_ROOT" ]; then ME=${SUDO_USER:-root}
else ME=$WHO; fi
case $ME in "" | -* | *[!A-Za-z0-9._-]*) echo "REFUSED: cannot use the user name '$ME'" >&2; exit 2 ;; esac
# The administrator: the account that ran this script (through sudo, SUDO_USER).
# It owns the checkout directory and Homebrew, and reads the agents root.
ADMIN=$WHO
[ -z "$IS_ROOT" ] || ADMIN=${SUDO_USER:-root}
BREW="$ROOT/opt/homebrew/bin/brew"

# as_user <command...>: run as the agents' user. From root that is `sudo -u`,
# which never prompts; as the user, the command runs as it is.
as_user() {
  if [ -n "$IS_ROOT" ] && [ "$ME" != root ]; then sudo -u "$ME" -H "$@"; else "$@"; fi
}
# as_admin <command...>: run as the administrator, Homebrew's owner. From root
# that is `sudo -u`; as the administrator, the command runs as it is.
as_admin() {
  if [ -n "$IS_ROOT" ] && [ "$ADMIN" != root ]; then sudo -u "$ADMIN" -H "$@"; else "$@"; fi
}
# can_as: whether this run can act as the agents' user (root, or that user itself).
can_as() { [ -n "$IS_ROOT" ] || [ "$ME" = "$WHO" ]; }

say() { printf '%-12s%s\n' "$1" "$2"; }
pass() { n_ok=$((n_ok + 1)); say ok "$1"; }
miss() { missing="$missing $1"; say MISSING "$1: $2"; }
unsup() { n_unsup=$((n_unsup + 1)); say UNSUPPORTED "$1: $2"; }
na() { say n/a "$1: $2"; }
unknown() { n_unknown=$((n_unknown + 1)); say unknown "$1: $2"; }
is_missing() { case " $missing " in *" $1 "*) return 0 ;; esac; return 1; }
first_line() { printf '%s\n' "$1" | sed -n 1p | cut -c1-72; }

# runnable <command>: on PATH, and not one of macOS's developer-tools stubs
# (/usr/bin/git, /usr/bin/python3) on a Mac without the Command Line Tools.
runnable() {
  _p=$(command -v "$1" 2>/dev/null) || return 1
  if [ "$OS" = Darwin ] && [ "$_p" = "$ROOT/usr/bin/$1" ] && ! xcode-select -p >/dev/null 2>&1; then return 1; fi
  return 0
}

# ver_ge <version> <major> <minor>: the version (3.14.4, v22.22.1) is at least major.minor
ver_ge() {
  _v=${1#v}; _maj=${_v%%.*}; _rest=${_v#*.}; _min=${_rest%%.*}
  case "$_maj.$_min" in *[!0-9.]* | .* | *.) return 1 ;; esac
  [ "$_maj" -gt "$2" ] || { [ "$_maj" -eq "$2" ] && [ "$_min" -ge "$3" ]; }
}

osrel() { sed -n "s/^$1=//p" "$ROOT/etc/os-release" 2>/dev/null | tr -d '"' | sed -n 1p; }

detect() {
  OS=$(uname -s 2>/dev/null) PM=none
  case $OS in
    Linux)
      ID=$(osrel ID) LIKE=$(osrel ID_LIKE) PRETTY=$(osrel PRETTY_NAME)
      case " $ID $LIKE " in
        *" debian "* | *" ubuntu "*) command -v apt-get >/dev/null 2>&1 && PM=apt ;;
      esac
      ;;
    Darwin)
      PRETTY="macOS $(uname -m 2>/dev/null)"
      [ "$(uname -m 2>/dev/null)" = arm64 ] && PM=brew
      ;;
  esac
}

tool() { # tool <command> <version args...>: present only if it RUNS, not merely exists
  if runnable "$1" && _out=$("$@" 2>&1); then pass "$1: $(first_line "$_out")"; else miss "$1" "not installed"; fi
}

check_node() {
  [ -n "$WITH_NODE" ] || { na node "not asked for (--with-node)"; return; }
  if ! runnable node || ! v=$(node --version 2>/dev/null); then miss node "not installed"; return; fi
  if ! ver_ge "$v" 22 0; then
    unsup node "node $v; agent-revive's sign-in driver needs 22 or newer, and this system's package is older"
  elif ! _npm=$(npm --version 2>/dev/null); then miss node "npm is not installed"
  else pass "node: $v, npm $_npm"; fi
}

check_claude() {
  if [ -n "$AGENTS_USER" ] && [ -z "$U_HOME" ]; then miss claude "not installed for $ME ($ME does not exist)"; return; fi
  if ! can_as; then unknown claude "for $ME: only root or $ME can run it; --install checks it as $ME"; return; fi
  if [ "$OS" = Linux ]; then
    if v=$(as_user bash -lc 'claude --version' 2>/dev/null) && [ -n "$v" ]; then
      pass "claude: $v (found by $ME's login shell)"
    elif v=$(as_user sh -c '"$HOME/.local/bin/claude" --version' 2>/dev/null); then
      miss claude-path "$v is in ~/.local/bin, which $ME's login PATH lacks; the agent units start it through bash -l"
    else
      miss claude "not installed for $ME"
    fi
  elif v=$(as_user bash -lc 'claude --version' 2>/dev/null) && [ -n "$v" ]; then
    pass "claude: $v (found by $ME's login shell)"
  elif v=$(as_user sh -c '"$HOME/.local/bin/claude" --version' 2>/dev/null); then
    miss claude-path "$v is in ~/.local/bin, which $ME's login PATH lacks; the session supervisor starts it through bash -l, which reads ~/.bash_profile"
  else
    miss claude "not installed for $ME"
  fi
}

user_fields() { # user_fields <passwd line>: U_UID, U_GID, U_HOME from it
  U_UID=$(printf '%s\n' "$1" | cut -d: -f3) U_GID=$(printf '%s\n' "$1" | cut -d: -f4)
  U_HOME=$(printf '%s\n' "$1" | cut -d: -f6)
}

# ds <key> <record output>: one attribute's value from `dscl . -read` output.
ds() { printf '%s\n' "$2" | sed -n "s/^$1: //p" | sed -n 1p; }

# lookup_user <name>: U_UID, U_GID, U_HOME of a user, or non-zero. macOS has no
# getent: its users are Directory Services records, read with dscl.
lookup_user() {
  if [ "$OS" = Darwin ]; then
    _r=$(dscl . -read "/Users/$1" UniqueID PrimaryGroupID NFSHomeDirectory 2>/dev/null) || return 1
    U_UID=$(ds UniqueID "$_r") U_GID=$(ds PrimaryGroupID "$_r") U_HOME=$(ds NFSHomeDirectory "$_r")
    [ -n "$U_UID" ]
  else
    _e=$(getent passwd "$1" 2>/dev/null) && [ -n "$_e" ] || return 1
    user_fields "$_e"
  fi
}

# group_gid <name>: a group's gid (macOS, dscl), or nothing.
group_gid() { ds PrimaryGroupID "$(dscl . -read "/Groups/$1" PrimaryGroupID 2>/dev/null)"; }

# The agents' user's password, from --agents-password-file: never printed.
read_password() {
  [ -n "$PWFILE" ] || return 1
  PW=$(sed -n 1p "$PWFILE" 2>/dev/null) && [ -n "$PW" ]
}

# run_secret <shown> <command...>: run a command that carries the password, echoing
# <shown>, the same command with the password replaced.
run_secret() {
  _shown=$1; shift
  echo "+ $_shown"
  "$@" >/dev/null || { _rc=$?; echo "FAILED: $_shown (exit $_rc); nothing after it ran" >&2; exit 1; }
}

# Automatic login for the agents' user (macOS): FileVault off, and the account
# that logs in at boot is $ME.
probe_autologin() {
  case $(fdesetup status 2>/dev/null) in
    *"FileVault is On"*)
      unsup autologin "FileVault is on, and macOS does not log in automatically while it is; the agents run in the session of the account that logs in at boot. Turn FileVault off (System Settings, Privacy & Security), then run --install --read-back <read-back file> again"
      return ;;
  esac
  _who=$(defaults read "$ROOT/Library/Preferences/com.apple.loginwindow" autoLoginUser 2>/dev/null)
  if [ "$_who" = "$ME" ]; then pass "autologin: $ME logs in automatically, so its launchd jobs start at boot"
  else miss autologin "${_who:-no account} logs in automatically, not $ME: the agents' launchd jobs run in $ME's session, which only its automatic login starts at boot"; fi
}

# Remote Login limited to com.apple.access_ssh (macOS): the agents' user is in it.
probe_ssh_access() {
  dscl . -read /Groups/com.apple.access_ssh >/dev/null 2>&1 || { pass "ssh-access: Remote Login admits every account"; return; }
  if dseditgroup -o checkmember -m "$ME" com.apple.access_ssh >/dev/null 2>&1; then
    pass "ssh-access: $ME is in com.apple.access_ssh"
  else
    miss ssh-access "Remote Login admits only com.apple.access_ssh, and $ME is not in it"
  fi
}

# The dedicated agents user (--agents-user): it exists, holds no sudo right,
# owns its agents root, and the person's key reaches it.
probe_agents() {
  if ! lookup_user "$ME"; then
    miss agents-user "$ME does not exist"
    [ "$OS" != Darwin ] || miss agents-group "no group $ME: the administrator reads the agents root through it"
    miss agents-root "${AGENTS_ROOT:-<home of $ME>/agents}, made with $ME"
    miss agents-ssh "no key: $ME does not exist"
    [ "$OS" != Darwin ] || miss ssh-access "$ME does not exist"
    probe_checkout "$AGENTS_ROOT"
    probe_admin_group
    return
  fi
  groups=$(id -nG "$ME" 2>/dev/null) bad=""
  for g in $groups; do case $g in sudo | admin | wheel) bad="$bad $g" ;; esac; done
  if [ -n "$bad" ]; then
    unsup agents-user "$ME is in group${bad}, which the distribution's sudoers lets run anything as root; the agents' user must have no sudo right: take it out of the group, or name another user"
  else
    pass "agents-user: $ME (uid $U_UID, home $U_HOME, groups: $groups)"
  fi
  if [ -z "$IS_ROOT" ]; then
    unknown agents-sudo "only root reads $ME's sudo rules; --install reads sudo -l -U $ME"
  elif ! command -v sudo >/dev/null 2>&1; then
    pass "agents-sudo: sudo is not installed"
  else
    l=$(LC_ALL=C sudo -l -U "$ME" 2>&1)
    case $l in
      *"may run the following commands"*) unsup agents-sudo "$ME has sudo rules (sudo -l -U $ME lists them); the agents' user must have none: remove them, or name another user" ;;
      *"is not allowed to run sudo"*) pass "agents-sudo: none ($ME may not run sudo)" ;;
      *) unsup agents-sudo "sudo -l -U $ME says neither that $ME may run commands nor that it may not: $(first_line "$l")" ;;
    esac
  fi
  AGID=$U_GID
  if [ "$OS" = Darwin ]; then
    AGID=$(group_gid "$ME")
    if [ -n "$AGID" ]; then pass "agents-group: group $ME (gid $AGID)"
    else miss agents-group "no group $ME: the administrator reads the agents root through it"; AGID=none; fi
  fi
  r=${AGENTS_ROOT:-$U_HOME/agents}
  if [ -d "$r" ]; then
    set -- $(ls -ndL "$r")
    if [ "$3" != "$U_UID" ]; then
      unsup agents-root "$r is owned by uid $3, not by $ME (uid $U_UID): the agents' user must own its root; name another, or change its owner by hand"
    elif [ "$4" != "$AGID" ] || [ "$1" != drwxr-x--- ]; then
      miss agents-root "$r is $1, group $4: the administrator reads it through $ME's group (gid $AGID), mode 750"
    else pass "agents-root: $r, owned by $ME, its group's to read, mode 750"; fi
  elif [ -e "$r" ]; then unsup agents-root "$r is not a directory"
  elif can_as; then miss agents-root "$r does not exist"
  else unknown agents-root "$r is not visible to $WHO; root or $ME can tell"; fi
  k="$U_HOME/.ssh/authorized_keys"
  if [ -s "$k" ]; then pass "agents-ssh: $k holds a key"
  elif can_as; then miss agents-ssh "no key in $k: SSH cannot reach $ME"
  else unknown agents-ssh "no key visible to $WHO in $k; root or $ME can tell"; fi
  [ "$OS" != Darwin ] || probe_ssh_access
  probe_checkout "$r"
  probe_admin_group
}

# The administrator in the agents user's group: it reads the agents root.
probe_admin_group() {
  if [ "$ADMIN" = "$ME" ] || [ "$ADMIN" = root ]; then
    na admin-group "no separate administrator to read $ME's agents root"
    return
  fi
  for g in $(id -nG "$ADMIN" 2>/dev/null); do
    [ "$g" = "$ME" ] && { pass "admin-group: $ADMIN is in $ME's group, so it reads the agents root"; return; }
  done
  miss admin-group "$ADMIN is not in $ME's group: fleet upgrade, run by $ADMIN, reads every install under the agents root"
}

# The administrator's checkout directory: outside the agents root <$1> (empty
# while the agents user, and so its default root, does not exist yet), the
# administrator's own, writable by nobody else.
probe_checkout() {
  _aroot=$1
  c=${CHECKOUT:-$ROOT/opt/agent-fleet}
  _save="$U_UID $U_GID $U_HOME"
  if lookup_user "$ADMIN"; then A_UID=$U_UID A_GID=$U_GID; else A_UID="" A_GID=""; fi
  set -- $_save; U_UID=${1:-} U_GID=${2:-} U_HOME=${3:-}
  [ -n "$_aroot" ] && case "$c/" in
    "$_aroot"/*) unsup checkout-dir "$c is inside the agents root $_aroot, where $ME could rename it away and put its own in its place; name one outside it (--checkout; the default is /opt/agent-fleet)"; return ;;
  esac
  if [ -d "$c" ]; then
    set -- $(ls -ndL "$c")
    case $1 in
      d???????w?* | d????w????*) unsup checkout-dir "$c is writable by its group or by everyone ($1); make it $ADMIN's alone (chmod 755)" ;;
      *) if [ "$3" = "$A_UID" ]; then pass "checkout-dir: $c, owned by $ADMIN, mode 755 or narrower"
         else unsup checkout-dir "$c is owned by uid $3, not by the administrator $ADMIN (uid $A_UID); name another, or change its owner by hand"; fi ;;
    esac
  elif [ -e "$c" ]; then unsup checkout-dir "$c is not a directory"
  else miss checkout-dir "$c does not exist: the administrator's, for the fleet checkout"; fi
}

probe_linux() {
  pass "system: $PRETTY, apt; agents' user $ME"
  tool git --version
  tool tmux -V
  tool curl --version
  py="$ROOT/usr/bin/python3"
  if [ -x "$py" ]; then
    v=$("$py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)
    if ver_ge "$v" 3 11; then
      pass "python3: /usr/bin/python3 $v"
    else
      unsup python3 "/usr/bin/python3 is ${v:-unreadable}; the fleet needs 3.11 or newer and its daemon units run /usr/bin/python3, so a second Python cannot stand in: use a release whose own python3 is 3.11+ (Ubuntu 24.04+, Debian 12+)"
    fi
  else
    miss python3 "/usr/bin/python3 is absent"
  fi
  check_node
  if [ -n "$WITH_BROWSER" ]; then
    absent=""
    for p in $BROWSER_PKGS; do
      [ "$(dpkg-query -W -f='${Status}' "$p" 2>/dev/null)" = "install ok installed" ] || absent="$absent $p"
    done
    if [ -z "$absent" ]; then pass "browser packages: $BROWSER_PKGS"; else miss browser "not installed:$absent"; fi
    na "chromium libraries" "not measured here; --install --with-browser runs Playwright's install-deps each time, and agent-revive's check launches the browser"
  else
    na browser "not asked for (--with-browser)"
  fi
  [ -z "$AGENTS_USER" ] || probe_agents
  if [ -e "$ROOT/var/lib/systemd/linger/$ME" ]; then pass "linger: on for $ME"; else miss linger "off for $ME"; fi
  check_claude
}

probe_macos() {
  pass "system: $PRETTY, Homebrew; agents' user $ME"
  [ -z "$AGENTS_USER" ] || probe_agents
  # Homebrew refuses to run as root, and --install runs as root: ask it as the agents' user.
  if [ -x "$BREW" ] && _out=$(as_user "$BREW" --version 2>&1); then
    pass "brew: $(first_line "$_out")"
    PATH="${BREW%/brew}:$PATH"
  else
    miss brew "not installed (Homebrew)"
  fi
  tool git --version
  tool tmux -V
  tool curl --version
  if runnable python3 && v=$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null) \
     && ver_ge "$v" 3 11; then
    pass "python3: $(command -v python3) $v"
  else
    miss python3 "no python3 3.11 or newer on PATH (Apple's is 3.9)"
  fi
  check_node
  na browser "macOS draws a headful browser through WindowServer, with nothing to install; a protected Mac agent signs in by token only"
  probe_autologin
  check_claude
}

probe() {
  n_ok=0 n_unsup=0 n_unknown=0 missing="" U_UID="" U_GID="" U_HOME=""
  detect
  case "$OS/$PM" in
    Linux/apt) probe_linux ;;
    Darwin/brew) probe_macos ;;
    Darwin/*) unsup system "$PRETTY: Homebrew supports macOS on Apple Silicon only" ;;
    Linux/*) unsup system "${PRETTY:-Linux} without apt; supported: Debian or Ubuntu" ;;
    *) unsup system "${OS:-unknown}; supported: Linux with apt (Debian, Ubuntu) and macOS on Apple Silicon" ;;
  esac
  set -- $missing
  if [ "$n_unknown" -gt 0 ]; then u=", $n_unknown unknown"; else u=""; fi
  echo "== check: $n_ok ok, $# missing, $n_unsup unsupported$u"
}

verdict() {
  [ "$n_unsup" -eq 0 ] || return 3
  [ -z "$missing" ] || return 1
  return 0
}

# --------------------------------------------------------------- install

WORK="" SUDOERS_MADE=""
cleanup() { [ -z "$SUDOERS_MADE" ] || rm -f "$SUDOERS"; [ -z "$WORK" ] || rm -rf "$WORK"; }

run() {
  echo "+ $*"
  "$@" || { _rc=$?; echo "FAILED: $* (exit $_rc); nothing after it ran" >&2; exit 1; }
}

fetch() { # fetch <file> <url>: download an installer to WORK/<file>, readable by the agents' user
  run curl -fsSL -o "$WORK/$1" "$2"
  chmod 644 "$WORK/$1"
}

install_linux() {
  pkgs=""
  for i in $missing; do
    case $i in
      git | tmux | python3) pkgs="$pkgs $i" ;;
      curl) pkgs="$pkgs curl ca-certificates" ;;
      node) pkgs="$pkgs nodejs npm" ;;
      browser) pkgs="$pkgs $BROWSER_PKGS" ;;
    esac
  done
  if [ -n "$pkgs" ]; then
    run env DEBIAN_FRONTEND=noninteractive apt-get update
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y $pkgs
  fi
  [ -z "$WITH_BROWSER" ] || run npx --yes "playwright@$PLAYWRIGHT_VERSION" install-deps chromium
  if is_missing agents-user; then
    run useradd --create-home --shell /bin/bash --user-group "$ME"
    ent=$(getent passwd "$ME") || { echo "FAILED: useradd ran, and getent passwd $ME finds nothing" >&2; exit 1; }
    user_fields "$ent"
  fi
  if is_missing agents-root; then
    r=${AGENTS_ROOT:-$U_HOME/agents}
    run mkdir -p "$r"
    run chown "$U_UID:$U_GID" "$r"
    run chmod 750 "$r"
  fi
  ! is_missing admin-group || run usermod -a -G "$ME" "$ADMIN"
  if is_missing checkout-dir; then
    c=${CHECKOUT:-$ROOT/opt/agent-fleet}
    run mkdir -p "$c"
    run chown "$A_UID:$A_GID" "$c"
    run chmod 755 "$c"
  fi
  if is_missing agents-ssh; then
    src="$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)/.ssh/authorized_keys"
    [ -s "$src" ] || { echo "FAILED: no key in $src to give $ME; install one in $U_HOME/.ssh/authorized_keys by hand" >&2; exit 1; }
    run mkdir -p "$U_HOME/.ssh"
    run cp "$src" "$U_HOME/.ssh/authorized_keys"
    run chmod 700 "$U_HOME/.ssh"
    run chmod 600 "$U_HOME/.ssh/authorized_keys"
    run chown "$U_UID:$U_GID" "$U_HOME/.ssh" "$U_HOME/.ssh/authorized_keys"
  fi
  ! is_missing linger || run loginctl enable-linger "$ME"
  if is_missing claude; then
    fetch claude-install.sh "$CLAUDE_URL"
    run as_user bash "$WORK/claude-install.sh"
  fi
  if { is_missing claude || is_missing claude-path; } && ! as_user bash -lc 'command -v claude' >/dev/null 2>&1; then
    echo "+ add ~/.local/bin to $ME's login PATH in ~/.profile"
    as_user sh -c 'printf "\n%s\n" "PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$HOME/.profile"' \
      || { echo "FAILED: writing $ME's ~/.profile" >&2; exit 1; }
  fi
}

install_macos() {
  if is_missing agents-user; then
    run_secret "sysadminctl -addUser $ME -fullName $ME -shell /bin/bash -home /Users/$ME -password <the password>" \
      sysadminctl -addUser "$ME" -fullName "$ME" -shell /bin/bash -home "/Users/$ME" -password "$PW"
    run createhomedir -c -u "$ME"
    lookup_user "$ME" || { echo "FAILED: sysadminctl ran, and dscl finds no $ME" >&2; exit 1; }
  fi
  if is_missing agents-group; then
    run dseditgroup -o create -r "$ME agents" "$ME"
  fi
  if is_missing agents-root; then
    r=${AGENTS_ROOT:-$U_HOME/agents} AGID=$(group_gid "$ME")
    [ -n "$AGID" ] || { echo "FAILED: no group $ME to give the agents root" >&2; exit 1; }
    run mkdir -p "$r"
    run chown "$U_UID:$AGID" "$r"
    run chmod 750 "$r"
  fi
  ! is_missing admin-group || run dseditgroup -o edit -a "$ADMIN" -t user "$ME"
  if is_missing checkout-dir; then
    c=${CHECKOUT:-$ROOT/opt/agent-fleet}
    run mkdir -p "$c"
    run chown "$A_UID:$A_GID" "$c"
    run chmod 755 "$c"
  fi
  if is_missing agents-ssh; then
    _save="$U_UID $U_GID $U_HOME"
    lookup_user "${SUDO_USER:-root}" && src="$U_HOME/.ssh/authorized_keys" || src=""
    set -- $_save; U_UID=$1 U_GID=$2 U_HOME=$3
    [ -s "$src" ] || { echo "FAILED: no key in ${src:-the home of the administrator} to give $ME; install one in $U_HOME/.ssh/authorized_keys by hand" >&2; exit 1; }
    run mkdir -p "$U_HOME/.ssh"
    run cp "$src" "$U_HOME/.ssh/authorized_keys"
    run chmod 700 "$U_HOME/.ssh"
    run chmod 600 "$U_HOME/.ssh/authorized_keys"
    run chown "$U_UID:$U_GID" "$U_HOME/.ssh" "$U_HOME/.ssh/authorized_keys"
  fi
  ! is_missing ssh-access || run dseditgroup -o edit -a "$ME" -t user com.apple.access_ssh
  if is_missing autologin; then
    run_secret "sysadminctl -autologin set -userName $ME -password <the password>" \
      sysadminctl -autologin set -userName "$ME" -password "$PW"
  fi
  if is_missing brew; then
    # As the administrator, never the agents user (the HOMEBREW property).
    fetch homebrew-install.sh "$BREW_URL"
    echo "+ grant $ADMIN passwordless sudo for Homebrew's installer only: $SUDOERS"
    SUDOERS_MADE=1
    mkdir -p "${SUDOERS%/*}"
    ( umask 337; printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$ADMIN" > "$SUDOERS" ) || { echo "FAILED: writing $SUDOERS" >&2; exit 1; }
    visudo -cf "$SUDOERS" >/dev/null || { echo "FAILED: visudo rejects $SUDOERS" >&2; exit 1; }
    run as_admin env NONINTERACTIVE=1 /bin/bash "$WORK/homebrew-install.sh"
    rm -f "$SUDOERS"
    echo "+ removed $SUDOERS"
    [ -x "$BREW" ] || { echo "FAILED: Homebrew's installer finished, but $BREW is absent" >&2; exit 1; }
    PATH="${BREW%/brew}:$PATH"
  fi
  formulas=""
  for i in $missing; do
    case $i in
      git | tmux | curl | node) formulas="$formulas $i" ;;
      python3) formulas="$formulas python" ;;
    esac
  done
  [ -z "$formulas" ] || run as_admin "$BREW" install $formulas
  if is_missing claude; then
    fetch claude-install.sh "$CLAUDE_URL"
    run as_user bash "$WORK/claude-install.sh"
  fi
  if { is_missing claude || is_missing claude-path; } && ! as_user bash -lc 'command -v claude' >/dev/null 2>&1; then
    echo "+ add ~/.local/bin and Homebrew to $ME's login PATH in ~/.bash_profile"
    as_user sh -c 'printf "\n%s\n" "export PATH=\"\$HOME/.local/bin:/opt/homebrew/bin:\$PATH\"" >> "$HOME/.bash_profile"' \
      || { echo "FAILED: writing $ME's ~/.bash_profile" >&2; exit 1; }
  fi
}

# keep_read_back: a copy of the read-back the install ran on, in the agents' user's
# ~/.config/agent-fleet/ (where `fleet install` writes the host settings), written
# as that user. Only after every refusal, so a refused run still changes nothing.
keep_read_back() {
  _kept=$(as_user sh -c 'f="$HOME/.config/agent-fleet/read-back.txt"; umask 077 && mkdir -p "${f%/*}" && cat > "$f" && echo "$f"' \
    < "$READ_BACK") || { echo "FAILED: keeping a copy of the read-back in $ME's ~/.config/agent-fleet" >&2; exit 1; }
  echo "+ kept a copy of the read-back at $_kept"
}

probe
verdict
rc=$?
[ "$MODE" = install ] || exit "$rc"
if [ "$rc" -eq 3 ]; then echo "== UNSUPPORTED: --install cannot fix the line(s) above" >&2; exit 3; fi
if [ "$rc" -eq 0 ] && [ -z "$WITH_BROWSER" ]; then keep_read_back; echo "== nothing to install"; exit 0; fi

needs_root=$WITH_BROWSER
for i in $missing; do
  case $i in git | tmux | curl | python3 | node | browser | linger | agents-*) [ "$OS" = Linux ] && needs_root=1 ;; brew) needs_root=1 ;; esac
  case $i in agents-* | admin-group | checkout-dir | ssh-access | autologin) [ "$OS" = Darwin ] && needs_root=1 ;; esac
done
if [ -n "$needs_root" ] && [ -z "$IS_ROOT" ]; then
  echo "REFUSED: this part needs root; run it as: sudo -S -p \"\" sh $0 --install --read-back <read-back file> ... (password on stdin)" >&2
  exit 2
fi
if [ -n "$IS_ROOT" ] && [ "$ME" = root ]; then
  echo "REFUSED: run --install through sudo from the agents' user, so SUDO_USER names them; agents never run as root" >&2
  exit 2
fi
if [ "$OS" = Darwin ] && [ "$ADMIN" = root ] && { is_missing brew || is_missing git || is_missing tmux \
     || is_missing curl || is_missing python3 || is_missing node; }; then
  echo "REFUSED: Homebrew and its formulas install as the administrator, and Homebrew refuses root: run --install through sudo from the administrator's account, so SUDO_USER names it; nothing was changed" >&2
  exit 2
fi
if [ "$OS" = Darwin ] && { is_missing agents-user || is_missing autologin; } && ! read_password; then
  echo "REFUSED: creating $ME's account and its automatic login on macOS need its password: --agents-password-file <file> (one line, readable by root); nothing was changed" >&2
  exit 2
fi

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM HUP
WORK=$(mktemp -d "${TMPDIR:-/tmp}/agent-fleet-bootstrap.XXXXXX") || { echo "FAILED: mktemp" >&2; exit 1; }
chmod 755 "$WORK"
if [ "$OS" = Linux ]; then install_linux; else install_macos; fi
keep_read_back
cleanup
WORK=""
echo "== installed; checking again"
probe
verdict
