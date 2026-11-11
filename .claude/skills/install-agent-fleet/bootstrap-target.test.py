#!/usr/bin/env python3
"""bootstrap-target.test.py - bootstrap-target.sh against fake machines, offline.

Usage: python3 .claude/skills/install-agent-fleet/bootstrap-target.test.py
       (tests/run-all.sh discovers and runs it; no network, no real install, no sudo)

Each scenario is a fake machine: a fake root (BOOTSTRAP_ROOT: /etc/os-release,
/usr/bin/python3, the linger directory, sudoers.d, Homebrew's prefix), a fake
HOME for the agents' user `ada`, and a PATH holding ONLY fakes plus the few
real utilities the script uses - so a real git, curl or sudo on the machine
running the test can never answer for the fake one. `id` is a fake too: it says
`ada`, or root when the scenario runs --install the way the skill does, under
one `sudo -S` with SUDO_USER=ada. Every fake records its argv, and the
installing fakes leave the artifact a real install would (a binary, a linger
file), so the script's closing re-check has something to find.

What it proves, per OS (Ubuntu with apt, macOS on Apple Silicon):
  1. --check lists what is missing and changes nothing: no sudo, no package
     manager, no download, no file written (a snapshot of the fake machine
     before and after).
  2. --install, as root through sudo, runs the expected commands - apt-get or
     brew with the right packages, loginctl enable-linger, Homebrew's and Claude
     Code's installers downloaded to a file and run AS ada - and exits 0 only
     by its second check. The only sudo it calls is `sudo -u ada -H`; any other
     sudo fails the run (exit 97 from the fake).
  3. --install refuses (exit 2) without root when it needs root, and as root
     without SUDO_USER; it reads nothing from stdin (a canary there never
     reaches the output or a command). Without a valid --read-back <file> it
     refuses (exit 2) before running any command, naming the skill's step-2
     message `Read back before install`, even as root under sudo the way the
     skill runs it: no --read-back, a file that is not there, an empty one, one
     whose first line is not exactly the heading, one with no answers after it,
     and the retired --read-back-sent flag, which must not install anything.
     Every other --install here carries a valid file (RB), the successful ones
     included, so "with it, it installs" is measured on the same machine; a run
     that passes the gate prints the file first and keeps a copy in the agents'
     user's ~/.config/agent-fleet/read-back.txt.
  4. Homebrew's temporary sudoers grant exists while its installer runs and is
     gone afterwards - also when that installer fails. Homebrew is the
     ADMINISTRATOR's: with --agents-user, its installer and `brew install` run
     as the administrator (SUDO_USER) and the grant names the administrator,
     never the agents user - whoever owns Homebrew's prefix can replace every
     program in it, the python3 the protected stall watchdog runs included. As
     root with no SUDO_USER (no administrator to install as), --install refuses
     (exit 2) and changes nothing. The browser libraries are installed with the
     Playwright version the sign-in driver's package-lock.json names, never an
     unpinned `npx playwright` run as root.
  5. Unsupported systems exit 3 under --install too, having run nothing: an old
     /usr/bin/python3, Linux without apt, macOS on Intel, an old Node.
  6. A failed download fails its step (exit 1) and nothing after it runs; a
     tool that exists but does not run is MISSING; macOS's developer-tools
     stubs are never run without the Command Line Tools.
  7. --agents-user: the admin `alan` (SUDO_USER) creates the agents user `ada`
     with useradd and nothing that names a group, so ada never gets sudo; its
     agents root is owned by it; alan's authorized_keys becomes ada's; lingering
     and Claude Code are ada's, not alan's; `sudo -l -U ada` is read as root
     and must say ada may run nothing; a second --install changes nothing.
     --check, as alan without root, says what it cannot know (unknown) instead
     of guessing. An agents user already in group sudo, already holding sudo
     rules, or an agents root someone else owns is UNSUPPORTED (exit 3) with
     nothing changed: the script never removes a right, it refuses.
  9. The administrator reads the agents root: --install puts alan (never ada)
     in ada's group with `usermod -a -G ada alan`, and the root is 750 in ada's
     group; a root ada owns with another mode is set to 750 (MISSING first).
  8. The fleet checkout's directory (checkout-dir, default /opt/agent-fleet
     under the fake root): --install makes it alan's, mode 755; one inside the
     agents root (where ada could rename the checkout away) or writable by its
     group is UNSUPPORTED (exit 3) with nothing changed.
 10. macOS: the agents' user must be the account that logs in automatically
     (autologin MISSING until it is; FileVault on is UNSUPPORTED, exit 3,
     nothing changed); --install needs --agents-password-file for that and for
     a new account, and refuses (exit 2, nothing changed) without it. With
     --agents-user, alan's --install creates ada as a STANDARD account with
     sysadminctl (no -admin), its home with createhomedir, a group ada with
     dseditgroup (macOS accounts share the primary group staff), the agents
     root ada's in group ada at 750, alan in group ada, alan's key for ada, ada
     in com.apple.access_ssh where Remote Login is limited to it, ada's
     automatic login, and ada's ~/.bash_profile PATH for claude; its second
     check finds nothing missing, and the password reaches no output line (the
     commands that take it are echoed with it replaced). The same install on a
     Mac without Homebrew installs Homebrew and its formulas as alan (item 4). The fake directory
     records (dscl, dseditgroup, sysadminctl, createhomedir, fdesetup, defaults)
     live in the fake root: etc/passwd and etc/fake-dsgroups/<group>.

The fake passwd, groups and sudo rules live in the fake root
(etc/passwd, etc/fake-groups/<user>, etc/fake-sudo-rules/<user>), read by the
fake getent, id and sudo. Every user in it has THIS process's uid and gid, so a
chown to that user is one a non-root test may make; the one scenario that needs
a foreign owner gives ada another uid.

THE CONTROLS. "Changed nothing" and "ran nothing" are absences, and an absence
proves something only if the instrument can see a presence: the same snapshot
and the same call log must show changes and calls after a successful --install
of the same machine (for the read-back refusals, the ubuntu machine's install
right after them, with a valid file). The "stub never run" check has its pair: the same stub is
recorded where it must run. The claude login-PATH finding has its pair: the
same fake claude is found with Ubuntu's ~/.profile. If a control does not fire,
the run is NO VERDICT (exit 3), never a pass.

Exit codes: 0 pass; 1 a check failed; 3 NO VERDICT.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "bootstrap-target.sh"
SH = shutil.which("sh")
REAL = ["sed", "tr", "cut", "cat", "cp", "chmod", "chown", "ls", "rm", "mkdir", "mktemp", "env", "bash", "sh"]
PROFILE_UBUNTU = 'if [ -d "$HOME/.local/bin" ] ; then\n    PATH="$HOME/.local/bin:$PATH"\nfi\n'
CANARY = "canary-sudo-password-7f3a"
failures, noverdict = [], []
# The step-2 message as the skill has the session save it: the heading, then the
# answers. RB is filled in main() with --read-back and the file's path.
READ_BACK = "Read back before install\nTarget: a physical Linux machine\nAgents user: ada\n"
RB = []

FAKE = r'''#!PYTHON
import json, os, subprocess, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
E = os.environ
ROOT, BIN, LOG = E["BOOTSTRAP_ROOT"], E["FAKE_BIN"], E["FAKE_LOG"]
def log(rec):
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
def fake(path, version):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!" + sys.executable + "\nprint(%r)\n" % version)
    os.chmod(path, 0o755)
def tool(path):
    with open(sys.argv[0]) as src, open(path, "w") as dst:
        dst.write(src.read())
    os.chmod(path, 0o755)
def passwd(user):
    try:
        with open(os.path.join(ROOT, "etc/passwd")) as f:
            for line in f:
                if line.split(":")[0] == user:
                    return line.rstrip("\n").split(":")
    except FileNotFoundError:
        pass
    return None
log([name] + args)
if name == "uname":
    print(E.get("FAKE_UNAME_S", "Linux") if args == ["-s"] else E.get("FAKE_UNAME_M", "x86_64"))
elif name == "id":
    if args[:1] == ["-nG"]:
        try:
            print(open(os.path.join(ROOT, "etc/fake-groups", args[1])).read().strip())
        except FileNotFoundError:
            print(args[1])
    else:
        print(E.get("FAKE_ID_U", "1000") if args == ["-u"] else E.get("FAKE_ID_UN", "ada"))
elif name == "getent":
    p = passwd(args[1]) if args[:1] == ["passwd"] and len(args) == 2 else None
    if p is None:
        sys.exit(2)
    print(":".join(p))
elif name == "usermod":
    # usermod -a -G <group> <user>: the group joins <user>'s list in etc/fake-groups.
    if args[:2] != ["-a", "-G"] or len(args) != 4:
        sys.exit(98)
    path = os.path.join(ROOT, "etc/fake-groups", args[3])
    try:
        have = open(path).read().split()
    except FileNotFoundError:
        have = [args[3]]
    with open(path, "w") as f:
        f.write(" ".join(have + [args[2]]) + "\n")
elif name == "useradd":
    user = args[-1]
    home = os.path.join(ROOT, "home", user)
    with open(os.path.join(ROOT, "etc/passwd"), "a") as f:
        f.write("%s:x:%d:%d::%s:/bin/bash\n" % (user, os.getuid(), os.getgid(), home))
    os.makedirs(home)
    with open(os.path.join(home, ".profile"), "w") as f:
        f.write(E.get("FAKE_SKEL_PROFILE", ""))
elif name == "sudo":
    if args[:2] == ["-l", "-U"] and len(args) == 3:
        if os.path.exists(os.path.join(ROOT, "etc/fake-sudo-rules", args[2])):
            print("User %s may run the following commands on fakehost:\n    (ALL) NOPASSWD: ALL" % args[2])
            sys.exit(0)
        print("User %s is not allowed to run sudo on fakehost." % args[2])
        sys.exit(int(E.get("FAKE_SUDO_L_RC", "1")))
    if len(args) < 4 or args[0] != "-u" or args[2] != "-H":
        sys.exit(97)
    p = passwd(args[1])
    env = dict(E, HOME=p[5] if p else E["FAKE_USER_HOME"], FAKE_AS_USER=args[1], FAKE_ID_U="1000",
               FAKE_ID_UN=args[1])
    sys.exit(subprocess.run(args[3:], env=env).returncode)
elif name == "visudo":
    with open(args[-1]) as f:
        sys.exit(0 if f.read().endswith("NOPASSWD: ALL\n") else 1)
elif name == "apt-get":
    log(["apt-get-env", "DEBIAN_FRONTEND=" + E.get("DEBIAN_FRONTEND", "")])
    if args[:2] == ["install", "-y"]:
        for p in args[2:]:
            if p in ("git", "tmux", "curl", "npm"):
                tool(os.path.join(BIN, p))
            elif p == "nodejs":
                tool(os.path.join(BIN, "node"))
            elif p == "python3":
                fake(os.path.join(ROOT, "usr/bin/python3"), E.get("FAKE_APT_PY", "3.14.4"))
            elif p != "ca-certificates":
                open(os.path.join(ROOT, "var/lib/fake-dpkg", p), "w").close()
elif name == "dpkg-query":
    if os.path.exists(os.path.join(ROOT, "var/lib/fake-dpkg", args[-1])):
        print("install ok installed", end="")
    else:
        sys.exit(1)
elif name == "loginctl":
    if args[0] == "enable-linger":
        open(os.path.join(ROOT, "var/lib/systemd/linger", args[1]), "w").close()
elif name == "curl":
    if args == ["--version"]:
        print("curl 8.0.0-fake")
    elif E.get("FAKE_CURL_FAIL"):
        sys.exit(22)
    else:
        out, url = args[args.index("-o") + 1], args[-1]
        with open(out, "w") as f:
            if url.endswith("claude.ai/install.sh"):
                f.write('mkdir -p "$HOME/.local/bin"\n'
                        'printf "#!/bin/sh\\necho \'9.9.9 (Claude Code)\'\\n" > "$HOME/.local/bin/claude"\n'
                        'chmod 755 "$HOME/.local/bin/claude"\n')
            else:
                f.write('s=absent; [ -e "$BOOTSTRAP_ROOT/etc/sudoers.d/agent-fleet-bootstrap" ] && s=present\n'
                        'g=$(cut -d" " -f1 "$BOOTSTRAP_ROOT/etc/sudoers.d/agent-fleet-bootstrap" 2>/dev/null)\n'
                        'printf "%s\\n" "[\\"homebrew-installer\\", \\"NONINTERACTIVE=$NONINTERACTIVE\\", '
                        '\\"as=$FAKE_AS_USER\\", \\"sudoers=$s\\", \\"grant=$g\\"]" >> "$FAKE_LOG"\n'
                        '[ -z "$FAKE_BREW_FAIL" ] || exit 1\n'
                        'cp "$FAKE_BIN/brew-template" "$BOOTSTRAP_ROOT/opt/homebrew/bin/brew"\n')
elif name in ("brew", "brew-template"):
    if E.get("FAKE_ID_U") == "0":
        sys.stderr.write("Error: Running Homebrew as root is extremely dangerous and no longer supported.\n")
        sys.exit(1)  # Homebrew refuses root; the script must run it as the agents' user
    if args == ["--version"]:
        print("Homebrew 9.0.0-fake")
    elif args[:1] == ["install"]:
        log(["brew-install-as", E.get("FAKE_AS_USER", "")])
        d = os.path.dirname(sys.argv[0])
        for p in args[1:]:
            if p == "python":
                fake(os.path.join(d, "python3"), "3.15.2")
            elif p == "node":
                tool(os.path.join(d, "node"))
                tool(os.path.join(d, "npm"))
            else:
                tool(os.path.join(d, p))
elif name == "dscl":
    # dscl . -read /Users/<n> <attrs>... | /Groups/<g> [attrs]
    rec = args[2] if len(args) > 2 else ""
    if rec.startswith("/Users/"):
        p = passwd(rec[len("/Users/"):])
        if p is None:
            sys.stderr.write("<dscl_cmd> DS Error: -14136 (eDSRecordNotFound)\n")
            sys.exit(56)
        vals = {"UniqueID": p[2], "PrimaryGroupID": p[3], "NFSHomeDirectory": p[5], "UserShell": p[6]}
        for a in args[3:] or list(vals):
            print("%s: %s" % (a, vals.get(a, "")))
    elif rec.startswith("/Groups/"):
        try:
            gid = open(os.path.join(ROOT, "etc/fake-dsgroups", rec[len("/Groups/"):])).read().split()[0]
        except (FileNotFoundError, IndexError):
            sys.stderr.write("<dscl_cmd> DS Error: -14136 (eDSRecordNotFound)\n")
            sys.exit(56)
        print("PrimaryGroupID: " + gid)
    else:
        sys.exit(98)
elif name == "dseditgroup":
    d = os.path.join(ROOT, "etc/fake-dsgroups")
    os.makedirs(d, exist_ok=True)
    g = args[-1]
    if args[:2] == ["-o", "create"]:
        open(os.path.join(d, g), "w").write("%d\n" % os.getgid())
    elif args[:2] == ["-o", "edit"] and args[2] == "-a" and args[4:6] == ["-t", "user"]:
        u = args[3]
        open(os.path.join(d, g), "a").write(u + "\n")
        gp = os.path.join(ROOT, "etc/fake-groups", u)
        os.makedirs(os.path.dirname(gp), exist_ok=True)
        have = open(gp).read().split() if os.path.exists(gp) else [u]
        open(gp, "w").write(" ".join(have + [g]) + "\n")
    elif args[:2] == ["-o", "checkmember"] and args[2] == "-m":
        try:
            members = open(os.path.join(d, g)).read().split()[1:]
        except FileNotFoundError:
            sys.exit(64)
        sys.exit(0 if args[3] in members else 1)
    else:
        sys.exit(98)
elif name == "sysadminctl":
    if args[:1] == ["-addUser"]:
        user, home = args[1], args[args.index("-home") + 1]
        with open(os.path.join(ROOT, "etc/passwd"), "a") as f:
            f.write("%s:x:%d:%d::%s:%s\n" % (user, os.getuid(), os.getgid(), ROOT + home,
                                            args[args.index("-shell") + 1]))
    elif args[:2] == ["-autologin", "set"]:
        open(os.path.join(ROOT, "etc/fake-autologin"), "w").write(args[args.index("-userName") + 1] + "\n")
    else:
        sys.exit(98)
elif name == "createhomedir":
    p = passwd(args[args.index("-u") + 1])
    os.makedirs(p[5], exist_ok=True)
elif name == "fdesetup":
    print("FileVault is %s." % ("On" if E.get("FAKE_FILEVAULT") == "on" else "Off"))
elif name == "defaults":
    try:
        print(open(os.path.join(ROOT, "etc/fake-autologin")).read().strip())
    except FileNotFoundError:
        sys.stderr.write("The domain/default pair of (com.apple.loginwindow, autoLoginUser) does not exist\n")
        sys.exit(1)
elif name == "xcode-select":
    rc = int(E.get("FAKE_CLT_RC", "2"))
    if rc == 0:
        print("/Library/Developer/CommandLineTools")
    sys.exit(rc)
elif name == "git":
    if E.get("FAKE_BROKEN") == "git":
        sys.exit(1)
    print("git version 0.0.0-fake")
elif name == "tmux":
    print("tmux 0.0-fake")
elif name == "node":
    print(E.get("FAKE_NODE", "v22.1.0"))
elif name == "npm":
    print("10.0.0")
'''


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


class Machine:
    """One fake machine; the agents' user is `ada`."""

    def __init__(self, base, name, os_release=None, uname=("Linux", "x86_64"), py=None, tools=(),
                 linger=False, claude=False, profile=PROFILE_UBUNTU, dpkg=(), apt=True):
        self.dir = base / name
        self.root, self.bin, self.home, self.tmp = (self.dir / d for d in ("root", "bin", "home", "tmp"))
        for d in (self.root / "etc", self.root / "usr/bin", self.root / "var/lib/systemd/linger",
                  self.root / "var/lib/fake-dpkg", self.root / "opt/homebrew/bin", self.bin, self.home, self.tmp,
                  self.dir / "real"):
            d.mkdir(parents=True, exist_ok=True)
        self.log = self.dir / "calls.jsonl"
        fake = FAKE.replace("PYTHON", sys.executable)
        for n in ["uname", "id", "sudo", "visudo", "dpkg-query", "loginctl", "npx", "brew-template",
                  "xcode-select", "getent", "useradd", "usermod", "dscl", "dseditgroup", "sysadminctl",
                  "createhomedir", "fdesetup", "defaults"] + (["apt-get"] if apt else []) + list(tools):
            (self.bin / n).write_text(fake)
            (self.bin / n).chmod(0o755)
        for r in REAL:
            os.symlink(shutil.which(r), self.dir / "real" / r)
        if os_release:
            (self.root / "etc/os-release").write_text(os_release)
        if py:
            self.put(self.root / "usr/bin/python3", f"print({py!r})\n")
        if linger:
            (self.root / "var/lib/systemd/linger/ada").touch()
        if claude:
            self.put(self.home / ".local/bin/claude", "print('9.9.9 (Claude Code)')\n")
        if profile is not None:
            (self.home / ".profile").write_text(profile)
        for p in dpkg:
            (self.root / "var/lib/fake-dpkg" / p).touch()
        self.uname = uname

    @staticmethod
    def put(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def snapshot(self):
        out = {}
        for top in (self.root, self.home, self.tmp, self.bin):
            for dirpath, dirs, files in os.walk(top):
                for f in dirs + files:
                    st = (Path(dirpath) / f).lstat()
                    out[str(Path(dirpath) / f)] = (st.st_mode, st.st_size, st.st_mtime_ns)
        return out

    def run(self, *args, root=False, sudo_user="ada", stdin="", path_tail="", **env):
        """As ada, or with root=True as root under sudo (SUDO_USER=sudo_user; None leaves it unset)."""
        if self.log.exists():
            self.log.unlink()
        e = {"PATH": f"{self.bin}:{self.dir / 'real'}{path_tail}", "HOME": str(self.home),
             "FAKE_USER_HOME": str(self.home), "TMPDIR": str(self.tmp), "BOOTSTRAP_ROOT": str(self.root),
             "FAKE_BIN": str(self.bin), "FAKE_LOG": str(self.log), "FAKE_UNAME_S": self.uname[0],
             "FAKE_UNAME_M": self.uname[1], "LANG": "C"}
        if root:
            e.update(FAKE_ID_U="0", FAKE_ID_UN="root", HOME=str(self.dir / "roothome"))
            if sudo_user:
                e["SUDO_USER"] = sudo_user
        e.update({k: v for k, v in env.items() if v is not None})
        r = subprocess.run([SH, str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=e,
                           timeout=120)
        calls = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return r, calls


def changing(calls):
    """Calls that install, elevate, download or write."""
    bad = []
    for c in calls:
        n = c[0]
        if c[:4] == ["sudo", "-u", "ada", "-H"] and (c[4:6] in (["bash", "-lc"], ["sh", "-c"])
                                                    or c[-1:] == ["--version"]):
            continue  # from root, a read-only probe run AS ada: a privilege drop, not an elevation
        if c[:3] == ["sudo", "-l", "-U"]:
            continue  # from root, a read-only listing of another user's sudo rules
        if n in ("sudo", "apt-get", "loginctl", "npx", "homebrew-installer", "visudo", "brew-install-as",
                 "useradd", "usermod", "sysadminctl", "createhomedir") or c[:3] in (["dseditgroup", "-o", "create"],
                                                                                    ["dseditgroup", "-o", "edit"]):
            bad.append(c)
        elif n == "curl" and "-o" in c:
            bad.append(c)
    return bad


def has(calls, *words):
    return any(all(w in c for w in words) for c in calls)


LOCKFILE = HERE.parent / "agent-revive" / "signin_driver" / "package-lock.json"


def playwright_version():
    """The Playwright version the sign-in driver's lockfile pins: what root's
    install-deps must run, so the libraries match the browser the driver drives."""
    try:
        v = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"]["node_modules/playwright"]["version"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        noverdict.append(f"the sign-in driver's lockfile names no playwright version ({LOCKFILE}: {exc})")
        return "<unknown>"
    return v


def tail(r):
    return (r.stderr or r.stdout).strip()[-300:]


UBUNTU = 'PRETTY_NAME="Ubuntu 26.04.1 LTS"\nID=ubuntu\nID_LIKE=debian\nVERSION_ID="26.04"\n'
UBUNTU_OLD = 'PRETTY_NAME="Ubuntu 22.04.5 LTS"\nID=ubuntu\nID_LIKE=debian\nVERSION_ID="22.04"\n'
FEDORA = 'PRETTY_NAME="Fedora Linux 44"\nID=fedora\n'


def ubuntu(base):
    m = Machine(base, "ubuntu-bare", os_release=UBUNTU)
    before = m.snapshot()
    r, calls = m.run("--check")
    check(r.returncode == 1, f"ubuntu --check on a bare machine exits 1 (got {r.returncode}: {tail(r)})")
    for item in ("git", "tmux", "curl", "python3", "linger", "claude"):
        check(f"MISSING     {item}:" in r.stdout, f"ubuntu --check lists {item} as MISSING")
    check("n/a         node:" in r.stdout, "ubuntu --check leaves node out unless --with-node")
    check(not changing(calls), f"ubuntu --check runs no sudo, package manager or download ({changing(calls)})")
    check(m.snapshot() == before, "ubuntu --check writes nothing")

    # The read-back gate, in the form the skill's step 4 runs --install (root,
    # under sudo, a password line on stdin) but without a valid read-back file.
    r, calls = m.run("--install", root=True, stdin=CANARY + "\n")
    check(r.returncode == 2 and "'Read back before install'" in r.stderr
          and "--install --read-back <read-back file>" in r.stderr and not calls and m.snapshot() == before,
          f"--install without --read-back is refused (exit 2) naming the step-2 message and the placeholder "
          f"invocation, before it runs any command, and writes nothing (got {r.returncode}, {len(calls)} call(s): "
          f"{tail(r)})")
    r, calls = m.run("--install", "--agents-user", "ada", "--with-node", root=True, sudo_user="alan")
    check(r.returncode == 2 and "'Read back before install'" in r.stderr and not calls and m.snapshot() == before,
          f"--install with every other option but --read-back is refused the same way (got {r.returncode})")
    # The retired flag: a copied command carrying it must install NOTHING.
    r, calls = m.run("--install", "--read-back-sent", root=True, stdin=CANARY + "\n")
    check(r.returncode == 2 and "--read-back <read-back file>" in r.stderr and not calls and m.snapshot() == before,
          f"--install --read-back-sent (the retired flag, no file) is refused with the usage line naming "
          f"--read-back <read-back file>, runs nothing and writes nothing (got {r.returncode}: {tail(r)})")
    rb_dir = m.dir / "read-backs"
    rb_dir.mkdir()
    bad = {"empty": ("", "is empty"),
           "wrong-head": ("Read back before installing\nAgents user: ada\n", "is not exactly 'Read back before install'"),
           "crlf-head": ("Read back before install\r\nAgents user: ada\r\n", "is not exactly 'Read back before install'"),
           "no-answers": ("Read back before install\n\n   \n", "lists no answers after its first line")}
    for name, (body, why) in bad.items():
        (rb_dir / name).write_text(body)
        r, calls = m.run("--install", "--read-back", str(rb_dir / name), root=True)
        check(r.returncode == 2 and why in r.stderr and "'Read back before install'" in r.stderr
              and not calls and m.snapshot() == before,
              f"--install --read-back <{name} file> is refused (exit 2, '{why}'), runs nothing, writes nothing "
              f"(got {r.returncode}: {tail(r)})")
    r, calls = m.run("--install", "--read-back", str(rb_dir / "absent"), root=True)
    check(r.returncode == 2 and "no readable file there" in r.stderr and not calls and m.snapshot() == before,
          f"--install --read-back <a path with no file> is refused, runs nothing, writes nothing (got {r.returncode})")

    r, calls = m.run("--install", *RB)
    check(r.returncode == 2 and "REFUSED: this part needs root" in r.stderr and not changing(calls)
          and m.snapshot() == before, f"--install without root, needing root, is refused and changes nothing "
                                      f"(got {r.returncode})")
    r, calls = m.run("--install", *RB, root=True, sudo_user=None)
    check(r.returncode == 2 and "SUDO_USER" in r.stderr and not changing(calls),
          f"--install as root with no SUDO_USER is refused: agents never run as root (got {r.returncode})")

    r, calls = m.run("--install", *RB, root=True, stdin=CANARY + "\n")
    check(r.returncode == 0, f"ubuntu --install as root under sudo exits 0 by its second check "
                             f"(got {r.returncode}: {tail(r)})")
    check(r.stdout.startswith(f"== read-back ({RB[1]}):\n{READ_BACK}== end of the read-back\n"),
          f"a valid read-back is printed at the top of the install's output, verbatim ({r.stdout[:200]!r})")
    kept = m.home / ".config/agent-fleet/read-back.txt"
    check(kept.is_file() and kept.read_text() == READ_BACK and stat.S_IMODE(kept.stat().st_mode) == 0o600
          and f"+ kept a copy of the read-back at {kept}" in r.stdout,
          "...and a copy is kept in the agents' user's ~/.config/agent-fleet/read-back.txt, mode 600, as ada")
    if not changing(calls) or m.snapshot() == before:
        noverdict.append("the ubuntu --install recorded no change, so '--check changed nothing' and 'the "
                         "read-back refusal changed nothing' prove nothing")
    check(["apt-get", "update"] in calls and ["apt-get-env", "DEBIAN_FRONTEND=noninteractive"] in calls
          and ["apt-get-env", "DEBIAN_FRONTEND="] not in calls,
          "ubuntu --install: apt-get update, every apt-get with DEBIAN_FRONTEND=noninteractive")
    check(["apt-get", "install", "-y", "git", "tmux", "curl", "ca-certificates", "python3"] in calls,
          "ubuntu --install: apt-get install -y git tmux curl ca-certificates python3")
    check(["loginctl", "enable-linger", "ada"] in calls, "ubuntu --install: loginctl enable-linger ada (SUDO_USER)")
    check(has(calls, "curl", "-fsSL", "-o", "https://claude.ai/install.sh"),
          "ubuntu --install: Claude Code's installer downloaded to a file, from the vendor's URL")
    check(any(c[:4] == ["sudo", "-u", "ada", "-H"] and c[4:5] == ["bash"] and c[-1].endswith("claude-install.sh")
              for c in calls), "ubuntu --install: Claude Code's installer runs as ada (sudo -u ada -H bash)")
    check((m.home / ".local/bin/claude").exists(), "ubuntu --install: claude lands in ada's ~/.local/bin")
    check(all(c[:4] == ["sudo", "-u", "ada", "-H"] for c in calls if c[0] == "sudo"),
          "ubuntu --install: every sudo it calls is sudo -u ada -H, which never prompts")
    check(CANARY not in r.stdout + r.stderr and not any(CANARY in json.dumps(c) for c in calls),
          "a line on stdin reaches neither the output nor any command: the script reads no stdin")
    check("== check: 7 ok, 0 missing, 0 unsupported" in r.stdout, "ubuntu --install's second check finds nothing missing")
    check(list(m.tmp.iterdir()) == [], f"ubuntu --install leaves no work directory ({list(m.tmp.iterdir())})")
    r, calls = m.run("--install", *RB)
    check(r.returncode == 0 and "nothing to install" in r.stdout and not changing(calls),
          "--install on a ready machine installs nothing and needs no root")

    # Claude Code found by the current shell but not by a login shell.
    m = Machine(base, "ubuntu-claude-path", os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl"),
                linger=True, claude=True, profile="")
    r, _ = m.run("--check")
    check(r.returncode == 1 and "MISSING     claude-path:" in r.stdout,
          "a claude only in ~/.local/bin, which ~/.profile does not add, is MISSING claude-path")
    r, calls = m.run("--install", *RB)
    check(r.returncode == 0 and 'PATH="$HOME/.local/bin:$PATH"' in (m.home / ".profile").read_text(),
          f"--install adds ~/.local/bin to ada's login PATH, without root (got {r.returncode}: {tail(r)})")
    m2 = Machine(base, "ubuntu-claude-ok", os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl"),
                 linger=True, claude=True)
    r, _ = m2.run("--check")
    if "ok          claude:" not in r.stdout:
        noverdict.append("with Ubuntu's ~/.profile the login shell did not find the fake claude, so the "
                         "claude-path finding above may be the environment, not the script")

    # --with-browser: agent-revive's packages, then Playwright's chromium libraries.
    m = Machine(base, "ubuntu-browser", os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl", "node", "npm"),
                linger=True, claude=True, dpkg=("jq", "xvfb"))
    r, calls = m.run("--check", "--with-browser")
    check(r.returncode == 1 and "MISSING     browser: not installed: x11vnc novnc websockify" in r.stdout,
          "--check --with-browser names the missing browser packages")
    r, calls = m.run("--install", *RB, "--with-browser", root=True)
    pw = playwright_version()
    check(r.returncode == 0 and ["apt-get", "install", "-y", "jq", "xvfb", "x11vnc", "novnc", "websockify"] in calls
          and ["npx", "--yes", f"playwright@{pw}", "install-deps", "chromium"] in calls
          and not any(c[:1] == ["npx"] and "playwright" in c for c in calls),
          f"--install --with-browser installs the packages and Playwright's chromium libraries, with the "
          f"Playwright the sign-in driver's lockfile names ({pw}), as root (got {r.returncode}: "
          f"{[c for c in calls if c[:1] == ['npx']]})")

    # A failed download fails its step; nothing after it runs.
    m = Machine(base, "ubuntu-download-fails", os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl"),
                linger=True)
    r, calls = m.run("--install", *RB, FAKE_CURL_FAIL="1")
    check(r.returncode == 1 and "FAILED: curl -fsSL -o" in r.stderr and not (m.home / ".local/bin/claude").exists()
          and not has(calls, "bash"), f"a failed installer download exits 1 naming the step, and no installer "
                                      f"runs (got {r.returncode})")

    # A tool that is present but does not run is MISSING, not ok.
    m = Machine(base, "ubuntu-broken-git", os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl"),
                linger=True, claude=True)
    r, _ = m.run("--check", FAKE_BROKEN="git")
    check(r.returncode == 1 and "MISSING     git:" in r.stdout, "a git that exits non-zero is MISSING, not ok")


ALAN_KEY = "ssh-ed25519 AAAAC3NzaFAKEFAKEFAKE alan@example\n"


def split_machine(base, name, ada=None, groups=None, rules=False):
    """Ubuntu with every package, administered by alan (whose key reaches it);
    ada, the agents user, exists only when `ada` gives its uid."""
    m = Machine(base, name, os_release=UBUNTU, py="3.14.4", tools=("git", "tmux", "curl"))
    alan = m.root / "home/alan"
    (alan / ".ssh").mkdir(parents=True)
    (alan / ".ssh/authorized_keys").write_text(ALAN_KEY)
    rows = [f"alan:x:{os.getuid()}:{os.getgid()}::{alan}:/bin/bash"]
    if ada is not None:
        home = m.root / "home/ada"
        home.mkdir(parents=True)
        (home / ".profile").write_text(PROFILE_UBUNTU)
        rows.append(f"ada:x:{ada}:{os.getgid()}::{home}:/bin/bash")
    (m.root / "etc/passwd").write_text("\n".join(rows) + "\n")
    for d in ("etc/fake-groups", "etc/fake-sudo-rules"):
        (m.root / d).mkdir(parents=True)
    if groups:
        (m.root / "etc/fake-groups/ada").write_text(groups + "\n")
    if rules:
        (m.root / "etc/fake-sudo-rules/ada").touch()
    return m


def split(base):
    m = split_machine(base, "split-bare")
    ada = m.root / "home/ada"
    before = m.snapshot()
    r, calls = m.run("--check", "--agents-user", "ada", FAKE_ID_UN="alan")
    check(r.returncode == 1, f"split --check as alan, ada absent, exits 1 (got {r.returncode}: {tail(r)})")
    for item in ("agents-user", "agents-root", "agents-ssh", "linger", "claude"):
        check(f"MISSING     {item}:" in r.stdout, f"split --check lists {item} as MISSING for ada")
    check("linger: off for ada" in r.stdout, "split --check reads ada's lingering, not alan's")
    check(not changing(calls) and m.snapshot() == before, "split --check runs nothing that changes and writes nothing")

    r, calls = m.run("--install", *RB, "--agents-user", "ada", root=True, sudo_user="alan",
                     FAKE_SKEL_PROFILE=PROFILE_UBUNTU)
    r1 = r
    check(r.returncode == 0, f"split --install as root under alan's sudo exits 0 by its second check "
                             f"(got {r.returncode}: {tail(r)})")
    if not changing(calls) or m.snapshot() == before:
        noverdict.append("the split --install recorded no change, so 'split --check changed nothing' proves nothing")
    adds = [c for c in calls if c[0] == "useradd"]
    check(adds == [["useradd", "--create-home", "--shell", "/bin/bash", "--user-group", "ada"]],
          f"split --install creates ada with useradd and no group option ({adds})")
    mods = [c for c in calls if c[0] == "usermod"]
    check(mods == [["usermod", "-a", "-G", "ada", "alan"]]
          and not any(c[0] in ("gpasswd", "adduser", "visudo") for c in calls)
          and not any(w in ("-G", "--groups", "sudo", "admin", "wheel") for c in adds for w in c)
          and not (m.root / "etc/sudoers.d").exists(),
          f"split --install gives ada no group and writes no sudoers file; its one usermod puts the ADMINISTRATOR "
          f"in ada's group ({mods})")
    check("admin-group: alan is in ada's group" in r.stdout,
          "split --install's re-check finds alan in ada's group, so alan reads the agents root")
    agents = ada / "agents"
    check(agents.is_dir() and agents.stat().st_uid == os.getuid() and (agents.stat().st_mode & 0o777) == 0o750,
          "split --install creates the agents root <ada's home>/agents, owned by ada, mode 750")
    keys = ada / ".ssh/authorized_keys"
    check(keys.is_file() and keys.read_text() == ALAN_KEY and (keys.stat().st_mode & 0o777) == 0o600
          and ((ada / ".ssh").stat().st_mode & 0o777) == 0o700,
          "split --install gives ada alan's authorized_keys (dir 700, file 600)")
    check(["loginctl", "enable-linger", "ada"] in calls and not (m.root / "var/lib/systemd/linger/alan").exists(),
          "split --install turns lingering on for ada, not for alan")
    check((ada / ".local/bin/claude").exists() and not (m.root / "home/alan/.local").exists()
          and any(c[:4] == ["sudo", "-u", "ada", "-H"] and c[-1].endswith("claude-install.sh") for c in calls),
          "split --install installs Claude Code for ada, as ada, and nothing in alan's home")
    check(["sudo", "-l", "-U", "ada"] in calls and "ok          agents-sudo:" in r.stdout,
          "split --install reads sudo -l -U ada as root and finds ada may run nothing")
    check("0 missing, 0 unsupported" in r.stdout, "split --install's second check finds nothing missing")
    opt = m.root / "opt/agent-fleet"
    check(opt.is_dir() and opt.stat().st_uid == os.getuid() and (opt.stat().st_mode & 0o777) == 0o755
          and f"+ chown {os.getuid()}:{os.getgid()} {opt}" in r1.stdout,
          "split --install makes the checkout directory /opt/agent-fleet alan's (the administrator's), mode 755")

    r, calls = m.run("--install", *RB, "--agents-user", "ada", root=True, sudo_user="alan")
    check(r.returncode == 0 and "nothing to install" in r.stdout and not changing(calls),
          f"a second split --install changes nothing (got {r.returncode}: {tail(r)})")
    for rc in ("0", "1"):
        r, _ = m.run("--check", "--agents-user", "ada", root=True, sudo_user="alan", FAKE_SUDO_L_RC=rc)
        check(r.returncode == 0 and "ok          agents-sudo:" in r.stdout,
              f"'not allowed to run sudo' is read from sudo's text, whatever its exit ({rc})")
    r, calls = m.run("--check", "--agents-user", "ada", FAKE_ID_UN="alan")
    check(r.returncode == 0 and "unknown     agents-sudo:" in r.stdout and "unknown     claude:" in r.stdout
          and not changing(calls),
          f"--check as alan, without root, reports ada's sudo rules and Claude Code as unknown "
          f"(got {r.returncode}: {tail(r)})")

    m = split_machine(base, "split-root-mode", ada=os.getuid())
    private = m.root / "home/ada/agents"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    r, _ = m.run("--check", "--agents-user", "ada", root=True, sudo_user="alan")
    check("MISSING     agents-root:" in r.stdout and "drwx------" in r.stdout,
          f"an agents root ada owns at mode 700 is MISSING: alan could not read it ({tail(r)})")
    r, _ = m.run("--install", *RB, "--agents-user", "ada", root=True, sudo_user="alan")
    check(r.returncode == 0 and (private.stat().st_mode & 0o777) == 0o750,
          f"--install sets it to 750, ada's group's to read (got {r.returncode}: {tail(r)})")

    m = split_machine(base, "split-root", ada=os.getuid())
    other = m.root / "srv/agents"
    r, _ = m.run("--install", *RB, "--agents-user", "ada", "--agents-root", str(other), root=True, sudo_user="alan")
    check(r.returncode == 0 and other.is_dir() and not (m.root / "home/ada/agents").exists(),
          f"--agents-root names the agents root instead of <home>/agents (got {r.returncode}: {tail(r)})")

    for name, kw, why in (
            ("split-sudo-group", dict(ada=os.getuid(), groups="ada sudo"), "UNSUPPORTED agents-user: ada is in group sudo"),
            ("split-sudo-rules", dict(ada=os.getuid(), rules=True), "UNSUPPORTED agents-sudo: ada has sudo rules"),
            ("split-foreign-root", dict(ada=os.getuid() + 1), "UNSUPPORTED agents-root:"),
            ("split-checkout-inside", dict(ada=os.getuid()), "UNSUPPORTED checkout-dir:"),
            ("split-checkout-shared", dict(ada=os.getuid()), "UNSUPPORTED checkout-dir:")):
        m = split_machine(base, name, **kw)
        extra = []
        if name == "split-foreign-root":
            (m.root / "home/ada/agents").mkdir()
        if name == "split-checkout-inside":
            (m.root / "home/ada/agents").mkdir()
            extra = ["--checkout", str(m.root / "home/ada/agents/fleet")]
        if name == "split-checkout-shared":
            (m.root / "opt/agent-fleet").mkdir(parents=True)
            (m.root / "opt/agent-fleet").chmod(0o775)
        before = m.snapshot()
        r, calls = m.run("--install", *RB, "--agents-user", "ada", *extra, root=True, sudo_user="alan")
        check(r.returncode == 3 and why in r.stdout and not changing(calls) and m.snapshot() == before,
              f"{name}: --install exits 3 with '{why}' and changes nothing (got {r.returncode}: {tail(r)})")

    m = split_machine(base, "split-usage")
    for bad in (["--agents-user", "root"], ["--agents-user", "Ada Lovelace"], ["--agents-user"],
                ["--agents-root", "/tmp/x"], ["--agents-user", "ada", "--agents-root", "relative"],
                ["--checkout", "/tmp/x"], ["--agents-user", "ada", "--checkout", "relative"]):
        r, calls = m.run("--check", *bad, FAKE_ID_UN="alan")
        check(r.returncode == 2 and not changing(calls), f"--check {' '.join(bad)} is refused (exit 2, got {r.returncode})")
    split_macos(base)


PASSWORD = "fixture-agents-password-31c"


def mac_split_machine(base, name, restricted_ssh=True, brew=True):
    """macOS on Apple Silicon administered by alan (whose key reaches it), with
    Homebrew and its formulas unless brew=False; ada does not exist yet."""
    m = Machine(base, name, uname=("Darwin", "arm64"), tools=("curl", "git", "tmux"), profile=None)
    if brew:
        b = m.root / "opt/homebrew/bin/brew"
        b.write_text((m.bin / "brew-template").read_text())
        b.chmod(0o755)
        Machine.put(m.root / "opt/homebrew/bin/python3", "print('3.14.4')\n")
    alan = m.root / "home/alan"
    (alan / ".ssh").mkdir(parents=True)
    (alan / ".ssh/authorized_keys").write_text(ALAN_KEY)
    (m.root / "etc/passwd").write_text(f"alan:x:{os.getuid()}:{os.getgid()}::{alan}:/bin/zsh\n")
    for d in ("etc/fake-groups", "etc/fake-sudo-rules", "etc/fake-dsgroups"):
        (m.root / d).mkdir(parents=True)
    if restricted_ssh:
        (m.root / "etc/fake-dsgroups/com.apple.access_ssh").write_text("399 alan\n")
    pw = m.dir / "agents-password"
    pw.write_text(PASSWORD + "\n")
    pw.chmod(0o600)
    return m, pw


def split_macos(base):
    m, pw = mac_split_machine(base, "split-macos")
    path = f":{m.root / 'opt/homebrew/bin'}"
    before = m.snapshot()
    r, calls = m.run("--check", "--agents-user", "ada", root=True, sudo_user="alan", path_tail=path)
    check(r.returncode == 1 and not changing(calls) and m.snapshot() == before,
          f"macOS split --check as root exits 1 and changes nothing (got {r.returncode}: {tail(r)})")
    for item in ("agents-user", "agents-group", "agents-root", "agents-ssh", "ssh-access", "admin-group",
                 "checkout-dir", "autologin"):
        check(f"MISSING     {item}:" in r.stdout, f"macOS split --check lists {item} as MISSING")
    check("n/a         browser:" in r.stdout and "linger" not in r.stdout,
          "macOS: the browser check is n/a, and there is no linger line (autologin is its counterpart)")
    r, calls = m.run("--install", *RB, "--agents-user", "ada", root=True, sudo_user="alan", path_tail=path)
    check(r.returncode == 2 and "--agents-password-file" in r.stderr and m.snapshot() == before,
          f"macOS --install without the password file is refused, exit 2, nothing changed (got {r.returncode}: {tail(r)})")
    r, calls = m.run("--install", *RB, "--agents-user", "ada", "--agents-password-file", str(pw), root=True,
                     sudo_user="alan", path_tail=path)
    check(r.returncode == 0 and "0 missing, 0 unsupported" in r.stdout,
          f"macOS split --install exits 0 by its second check, nothing missing (got {r.returncode}: {tail(r)})")
    add = [c for c in calls if c[:2] == ["sysadminctl", "-addUser"]]
    check(len(add) == 1 and add[0][1:] == ["-addUser", "ada", "-fullName", "ada", "-shell", "/bin/bash", "-home",
                                           "/Users/ada", "-password", PASSWORD] and "-admin" not in add[0],
          f"ada is created as a STANDARD account (no -admin), shell /bin/bash, home /Users/ada ({add})")
    check(["createhomedir", "-c", "-u", "ada"] in calls, "ada's home is created with createhomedir")
    check(["dseditgroup", "-o", "create", "-r", "ada agents", "ada"] in calls
          and ["dseditgroup", "-o", "edit", "-a", "alan", "-t", "user", "ada"] in calls
          and ["dseditgroup", "-o", "edit", "-a", "ada", "-t", "user", "com.apple.access_ssh"] in calls,
          "group ada is created, alan joins it, and ada joins com.apple.access_ssh")
    check(["sysadminctl", "-autologin", "set", "-userName", "ada", "-password", PASSWORD] in calls
          and (m.root / "etc/fake-autologin").read_text().strip() == "ada",
          "ada becomes the account that logs in automatically")
    leaked = [l for l in (r.stdout + r.stderr).splitlines() if PASSWORD in l]
    check(not leaked and r.stdout.count("<the password>") == 2,
          f"the password reaches no output line; both commands that take it are echoed with it replaced ({leaked})")
    ada = m.root / "Users/ada"
    root_dir = ada / "agents"
    st = root_dir.stat() if root_dir.exists() else None
    check(st is not None and oct(st.st_mode & 0o777) == "0o750" and st.st_gid == os.getgid(),
          f"the agents root is ada's, in group ada, mode 750 ({oct(st.st_mode) if st else 'absent'})")
    check((ada / ".ssh/authorized_keys").read_text() == ALAN_KEY, "alan's key reaches ada")
    prof = (ada / ".bash_profile").read_text() if (ada / ".bash_profile").exists() else ""
    check('export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"' in prof and "claude: 9.9.9" in r.stdout,
          "ada's ~/.bash_profile puts claude (and Homebrew) on the login PATH, and the second check finds claude there")
    check(all(c[:4] == ["sudo", "-u", "ada", "-H"] or c[1:] == ["-l", "-U", "ada"] for c in calls if c[0] == "sudo"),
          "macOS split --install: every sudo it calls is sudo -u ada -H, or the read-only sudo -l -U ada")
    r, calls = m.run("--install", *RB, "--agents-user", "ada", "--agents-password-file", str(pw), root=True,
                     sudo_user="alan", path_tail=path)
    check(r.returncode == 0 and "== nothing to install" in r.stdout and not changing(calls),
          f"a second macOS --install changes nothing (got {r.returncode}: {tail(r)})")

    # Homebrew absent: it is installed as the ADMINISTRATOR, alan, never as ada.
    m, pw = mac_split_machine(base, "split-macos-no-brew", brew=False)
    path = f":{m.root / 'opt/homebrew/bin'}"
    r, calls = m.run("--install", *RB, "--agents-user", "ada", "--agents-password-file", str(pw), root=True,
                     sudo_user="alan", path_tail=path)
    sudoers = m.root / "etc/sudoers.d/agent-fleet-bootstrap"
    installers = [c for c in calls if c[:1] == ["homebrew-installer"]]
    check(r.returncode == 0 and "0 missing, 0 unsupported" in r.stdout,
          f"macOS split --install without Homebrew exits 0 by its second check (got {r.returncode}: {tail(r)})")
    check(installers == [["homebrew-installer", "NONINTERACTIVE=1", "as=alan", "sudoers=present", "grant=alan"]],
          f"Homebrew's installer runs once, as alan, under a sudo grant naming alan, never ada ({installers})")
    check(not sudoers.exists(), "the temporary sudoers grant is removed")
    check(["brew-install-as", "alan"] in calls and ["brew-install-as", "ada"] not in calls
          and has(calls, "brew", "install", "python"),
          "brew install runs as alan, Homebrew's owner, never as ada")
    check(any(c[:4] == ["sudo", "-u", "ada", "-H"] and c[-1].endswith("claude-install.sh") for c in calls),
          "Claude Code is still ada's, installed as ada")
    as_alan = [c for c in calls if c[:4] == ["sudo", "-u", "alan", "-H"]]
    check(all(c[:4] in (["sudo", "-u", "ada", "-H"], ["sudo", "-u", "alan", "-H"]) or c[1:] == ["-l", "-U", "ada"]
              for c in calls if c[0] == "sudo")
          and len(as_alan) == 2 and as_alan[0][4:6] == ["env", "NONINTERACTIVE=1"]
          and as_alan[1][-2:] == ["install", "python"],
          f"the only things run as alan are Homebrew's installer, then brew install ({as_alan})")
    # As root with no SUDO_USER there is no administrator to install Homebrew as.
    m, pw = mac_split_machine(base, "split-macos-no-brew-no-admin", brew=False)
    before = m.snapshot()
    r, calls = m.run("--install", *RB, "--agents-user", "ada", "--agents-password-file", str(pw), root=True,
                     sudo_user=None, path_tail=f":{m.root / 'opt/homebrew/bin'}")
    check(r.returncode == 2 and "Homebrew" in r.stderr and "SUDO_USER" in r.stderr and not changing(calls)
          and m.snapshot() == before,
          f"--install as root with no SUDO_USER and no Homebrew is refused, exit 2, nothing changed "
          f"(got {r.returncode}: {tail(r)})")

    m, pw = mac_split_machine(base, "split-macos-filevault")
    before = m.snapshot()
    r, calls = m.run("--install", *RB, "--agents-user", "ada", "--agents-password-file", str(pw), root=True,
                     sudo_user="alan", path_tail=f":{m.root / 'opt/homebrew/bin'}", FAKE_FILEVAULT="on")
    check(r.returncode == 3 and "UNSUPPORTED autologin: FileVault is on" in r.stdout and not changing(calls)
          and m.snapshot() == before,
          f"FileVault on: autologin UNSUPPORTED, exit 3, nothing changed (got {r.returncode}: {tail(r)})")


def unsupported(base):
    for name, kw, extra, why in (
            ("ubuntu-old-python", dict(os_release=UBUNTU_OLD, py="3.10.12"), (),
             "UNSUPPORTED python3: /usr/bin/python3 is 3.10.12"),
            ("fedora", dict(os_release=FEDORA, apt=False), (), "UNSUPPORTED system: Fedora Linux 44 without apt"),
            ("macos-intel", dict(uname=("Darwin", "x86_64")), (), "UNSUPPORTED system: macOS x86_64"),
            ("ubuntu-old-node", dict(os_release=UBUNTU, py="3.14.4", tools=("node", "npm")), ("--with-node",),
             "UNSUPPORTED node: node v18.19.1")):
        m = Machine(base, name, **kw)
        before = m.snapshot()
        r, calls = m.run("--install", *RB, *extra, root=True, FAKE_NODE="v18.19.1")
        check(r.returncode == 3 and why in r.stdout and not changing(calls) and m.snapshot() == before,
              f"{name}: --install exits 3 with '{why}' and runs nothing (got {r.returncode}, "
              f"{len(changing(calls))} changing call(s))")


def macos(base):
    # The developer-tools stubs: never run without the Command Line Tools, and not counted as git.
    m = Machine(base, "macos-stub", uname=("Darwin", "arm64"), tools=("curl",))
    Machine.put(m.root / "usr/bin/git", "import json, os\nopen(os.environ['FAKE_LOG'], 'a').write("
                                        "json.dumps(['stub-git']) + '\\n')\nraise SystemExit(1)\n")
    r, calls = m.run("--check", path_tail=f":{m.root / 'usr/bin'}")
    check("MISSING     git:" in r.stdout and ["stub-git"] not in calls,
          "on a Mac without the Command Line Tools, /usr/bin/git is MISSING and never run")
    r, calls = m.run("--check", path_tail=f":{m.root / 'usr/bin'}", FAKE_CLT_RC="0")
    if ["stub-git"] not in calls:
        noverdict.append("the stub git was not recorded even where it must run, so 'never run' proves nothing")
    check("MISSING     git:" in r.stdout, "a /usr/bin/git that runs and fails is MISSING")
    Machine.put(m.root / "usr/bin/git", "print('git version 2.50.1 (Apple Git-155)')\n")
    r, calls = m.run("--check", path_tail=f":{m.root / 'usr/bin'}", FAKE_CLT_RC="0")
    check("ok          git: git version 2.50.1 (Apple Git-155)" in r.stdout,
          "with the Command Line Tools installed, Apple's git counts")

    # Homebrew's installer fails: the temporary sudoers grant is removed anyway.
    m = Machine(base, "macos-brew-fails", uname=("Darwin", "arm64"), tools=("curl",))
    (m.root / "etc/fake-autologin").write_text("ada\n")
    r, calls = m.run("--install", *RB, root=True, FAKE_BREW_FAIL="1")
    sudoers = m.root / "etc/sudoers.d/agent-fleet-bootstrap"
    check(r.returncode == 1 and has(calls, "homebrew-installer", "sudoers=present") and not sudoers.exists(),
          f"a failing Homebrew installer exits 1 and its sudoers grant is gone (got {r.returncode}, "
          f"grant {'LEFT BEHIND' if sudoers.exists() else 'removed'})")

    # macOS on Apple Silicon, freshly installed (macOS ships curl).
    m = Machine(base, "macos-bare", uname=("Darwin", "arm64"), tools=("curl",))
    before = m.snapshot()
    r, calls = m.run("--check")
    check(r.returncode == 1, f"macos --check on a bare machine exits 1 (got {r.returncode}: {tail(r)})")
    for item in ("brew", "git", "tmux", "python3", "claude", "autologin"):
        check(f"MISSING     {item}:" in r.stdout, f"macos --check lists {item} as MISSING")
    check("linger" not in r.stdout, "macos --check has no linger line: automatic login is its counterpart")
    check(not changing(calls) and m.snapshot() == before,
          "macos --check runs no sudo, installer or download and writes nothing")
    r, calls = m.run("--install", *RB)
    check(r.returncode == 2 and "needs root" in r.stderr and m.snapshot() == before,
          f"macos --install without root, Homebrew missing, is refused and changes nothing (got {r.returncode})")
    r, calls = m.run("--install", *RB, root=True)
    check(r.returncode == 2 and "--agents-password-file" in r.stderr and m.snapshot() == before,
          f"macos --install with automatic login missing and no password file: refused, nothing changed "
          f"(got {r.returncode}: {tail(r)})")
    pw = m.dir / "agents-password"
    pw.write_text(PASSWORD + "\n")
    r, calls = m.run("--install", *RB, "--agents-password-file", str(pw), root=True)
    check(r.returncode == 0, f"macos --install as root under sudo exits 0 by its second check "
                             f"(got {r.returncode}: {tail(r)})")
    check(["sysadminctl", "-autologin", "set", "-userName", "ada", "-password", PASSWORD] in calls
          and PASSWORD not in r.stdout + r.stderr,
          "macos --install makes ada (the login user, no --agents-user) the automatic-login account, password unprinted")
    if not changing(calls):
        noverdict.append("the macos --install recorded no change, so '--check changed nothing' proves nothing")
    check(has(calls, "curl", "-o", "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"),
          "macos --install: Homebrew's installer downloaded to a file, from its documented URL")
    check(["homebrew-installer", "NONINTERACTIVE=1", "as=ada", "sudoers=present", "grant=ada"] in calls,
          "macos --install: Homebrew's installer runs as ada (the login user and administrator, no "
          "--agents-user), unattended, with the temporary sudo grant naming ada")
    check(not sudoers.exists() and not (m.root / "etc/sudoers.d/agent-fleet-bootstrap").exists(),
          "macos --install: the temporary sudoers grant is removed")
    check(["brew-install-as", "ada"] in calls and has(calls, "brew", "install", "git", "tmux", "python"),
          "macos --install: brew install git tmux python, as ada")
    check(any(c[:4] == ["sudo", "-u", "ada", "-H"] and c[-1].endswith("claude-install.sh") for c in calls),
          "macos --install: Claude Code's installer runs as ada")
    check(all(c[:4] == ["sudo", "-u", "ada", "-H"] for c in calls if c[0] == "sudo"),
          "macos --install: every sudo it calls is sudo -u ada -H")
    check("0 missing, 0 unsupported" in r.stdout, "macos --install's second check finds nothing missing")


def main():
    missing = [r for r in REAL if not shutil.which(r)]
    if missing or not SH:
        print(f"NO VERDICT: real utilities missing on this machine: {missing or ['sh']}")
        return 3
    with tempfile.TemporaryDirectory(prefix="bootstrap-test-") as tmp:
        base = Path(tmp)
        (base / "read-back.txt").write_text(READ_BACK)
        RB[:] = ["--read-back", str(base / "read-back.txt")]
        ubuntu(base)
        split(base)
        unsupported(base)
        macos(base)
    if noverdict:
        print("NO VERDICT: " + "; ".join(noverdict))
        return 3
    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
