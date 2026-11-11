# Target: a physical Linux machine

Claude walks the person through making a Linux machine reachable over SSH from
the local machine - starting, when it is fresh or factory-reset, from installing
the system. That is the whole of this guide: once `ssh` answers with the
person's key, the common steps of this skill's `SKILL.md` drive the machine over
SSH, and `../bootstrap-target.sh` installs every package the fleet needs.

Placeholders: `<address>` (the machine's address on the person's network) and
`<user>` (the login the person administers the machine with; the one the
installer creates serves, and its sudo makes it the administrator - the agents
run as a separate user without sudo, which the bootstrap creates).

---

## 1. The supported system

**Ubuntu Server 26.04 LTS, amd64.** The fleet's CI runs every test, the
structural gates and the leak check on Ubuntu 26.04 with Python 3.14 and Node
22, on an arm64 machine (CONTRIBUTING.md section 9). What CI does not cover is
amd64 itself: no CI run uses an amd64 build, so the architecture-specific
pieces of an amd64 host, such as the `linux_x64` gitleaks build and the amd64
Chromium the sign-in driver downloads, are exercised by no CI run. Ubuntu 26.04
packages every dependency itself, Python 3.14 and Node 22 included.

**Any Debian or Ubuntu release whose own `/usr/bin/python3` is 3.11 or newer**
passes `bootstrap-target.sh --check` (Ubuntu 24.04 and later, Debian 12 and
later); nothing tests them. The floor is measured (2026-11-06): the whole test
suite and the structural gates were run with each of CPython 3.10, 3.11, 3.12,
3.13 and 3.14 as `python3`. 3.11 to 3.14 give the same result as 3.14. 3.10
fails: `scheduled-tasks/sched.py` uses `ast.TryStar` (new in 3.11) and stops at
import, and the signing packages `google-spreadsheet` pins require 3.11 to
install. It is the distribution's own python3 that counts, because the daemon
units run `/usr/bin/python3`.

## 2. Install the system (the person, at the machine)

Only for a machine that is fresh, factory-reset or being wiped; a machine
already running Ubuntu or Debian skips to section 3.

1. Download Ubuntu Server 26.04 LTS for amd64 from
   https://ubuntu.com/download/server, write it to a USB stick and boot the
   machine from it. Back up anything on its disk first: the next step erases it.
2. In the installer: use the entire disk; create the account `<user>`; tick
   **Install OpenSSH server**. Add nothing else.
3. After the first boot, log in at the console and read the address:
   `ip -4 addr show scope global`. That is `<address>`.

## 3. SSH (the person at the machine, then Claude on the local machine)

1. **An SSH server**, on a machine whose installer did not add one: at the
   machine, `sudo apt-get install -y openssh-server`. It starts at once and at
   every boot.
2. **A key on the local machine**: `ls ~/.ssh/id_ed25519.pub`, and when there is
   none, `ssh-keygen -t ed25519` (the person chooses a passphrase or none).
3. **The key on the machine**: `ssh-copy-id <user>@<address>`, from the local
   machine. It asks for `<user>`'s password once, at ssh's own prompt. Either
   the person runs it in their own terminal, or - with the password the person
   pasted into the session, kept in a local file of mode 600 - Claude runs it
   through ssh's askpass hook, which reads no terminal (OpenSSH 8.4 or newer
   on the local machine):

   ```bash
   printf '#!/bin/sh\ncat <password file>\n' > <helper> && chmod 700 <helper>
   SSH_ASKPASS=<helper> SSH_ASKPASS_REQUIRE=force ssh-copy-id -o StrictHostKeyChecking=accept-new \
     -o NumberOfPasswordPrompts=1 <user>@<address> < /dev/null
   rm -f <helper>
   ```

   The helper holds the file's path, never the password. `accept-new` is
   required: under `force` the first connection's host-key question would also
   go to the helper. One prompt, so a wrong password fails at once instead of
   retrying. The same file then feeds the sudo of `bootstrap-target.sh
   --install --read-back <read-back file>` (its header), so the person gives
   the password once.
4. **The check**: `ssh -o BatchMode=yes <user>@<address> true` exits 0.
   `BatchMode` refuses to ask for a password, so a 0 proves the key works.

**The target is ready: `<admin-host>` is `<user>@<address>`.** `<user>`'s sudo
asks for that same password, which `../bootstrap-target.sh --install
--read-back <read-back file>` receives once, on stdin, through `sudo -S` (its header). A `<user>` with no sudo at all
is the one install with no administrator (`../SKILL.md`, "Two users on the
target"). A machine
that is not always on the same network address needs a fixed one - a DHCP
reservation in the router - or `<host>` stops answering after a restart.

## 4. Size (every target)

Measured 2026-11-06 on one running fleet host, every agent with a live session,
read from systemd's per-unit accounting and `/proc`, aggregates only. A sample
of one install, not a law; re-measure on your own host once agents run.

| Per agent | Mean | Highest |
|---|---|---|
| the Claude Code session process, resident plus swapped | 0.87 GiB | 1.52 GiB |
| its three daemons (scheduler, chat watcher, stall watchdog) together | 37 MiB | 42 MiB |
| CPU, averaged over the agent unit's lifetime | 0.34 cores | 1.11 cores |

**The project's own work comes on top, and it is usually the larger term**:
the builds, test runs and emulators the agents start count against the same
machine. On the measured host, whose project runs heavy builds and test suites,
the agent units' memory peaks including that work had a median of 39 GiB per
agent; a project like that needs far more than the size below.

The rule: **RAM = 2 GiB for the system + 1.6 GiB per agent (the measured
maximum, rounded up) + the largest build or test run the project does at one
time.** The recommended size, **4 vCPU, 16 GiB RAM and a 100 GiB disk**, fits
**4 agents** with about 7.5 GiB left for one project build or test run at a
time, and their average CPU (about 1.4 cores) with room for a build. A project
whose heaviest job needs more moves up a size by the rule. The fleet itself
takes little disk - its checkout with the Node sub-package is about 0.7 GB, and
Claude Code about 0.33 GB per installed version - so the disk is for the
project's checkouts, one per agent, and their build output.
