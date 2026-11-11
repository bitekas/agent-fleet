# Target: a physical macOS machine

Claude guides the person through making a Mac reachable over SSH from the local
machine with the person's key. That is the whole of this guide: the common
steps of this skill's `SKILL.md` then drive the Mac over SSH, and
`../bootstrap-target.sh` installs Homebrew, git, tmux, Python and Claude Code
on it. The last section is about a Mac used the other way, as the LOCAL machine
that drives a cloud or Linux target.

Placeholders: `<address>` (the Mac's address on the person's network, or its
`<computer-name>.local` name) and `<user>` (the macOS account the person
administers the Mac with; section 5 says which account runs the agents).

---

## 1. What the Mac needs

- **Apple Silicon.** Homebrew's installer supports macOS on Apple Silicon only
  (its `install.sh`, checked 2026-11-06), and `bootstrap-target.sh --check`
  reports an Intel Mac as UNSUPPORTED.
- **macOS 13 or newer**, the oldest Claude Code supports
  (https://code.claude.com/docs/en/setup, checked 2026-11-06).
- **`<user>` is an administrator** (System Settings, Users and Groups): Homebrew
  installs only for an administrator, once, through the sudo that
  `bootstrap-target.sh --install --read-back <read-back file>` runs under. It
  stays `<user>`'s: with a separate agents user (section 5), Homebrew and its
  formulas are installed as `<user>`, never as the agents user, which runs
  Homebrew's programs and cannot change them.

A freshly reset Mac comes up in Setup Assistant: the person completes it at the
Mac and creates `<user>` there; the first account it creates is an
administrator.

## 2. Remote Login (the person, at the Mac)

1. **System Settings, General, Sharing, Remote Login**: on. Under its info
   button, **Allow access for**: only `<user>`.
2. The same pane shows the command to log in remotely, `ssh <user>@<name>.local`.
   On a network where `.local` names do not resolve, the address is
   `ipconfig getifaddr en0` (or `en1` for Wi-Fi on some models), at the Mac.

## 3. The key (Claude, on the local machine)

1. A key on the local machine: `ls ~/.ssh/id_ed25519.pub`, else
   `ssh-keygen -t ed25519`.
2. `ssh-copy-id <user>@<address>`: it asks for `<user>`'s password once, at
   ssh's own prompt. Either
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
3. `ssh -o BatchMode=yes <user>@<address> true` exits 0. `BatchMode` refuses to
   ask for a password, so a 0 proves the key works.

**The target is reachable: `<admin-host>` is `<user>@<address>`.** `<user>`'s
sudo asks for the account password, which `bootstrap-target.sh --install
--read-back <read-back file>` receives the way its header says: once, on stdin,
never in a command line.

## 4. Keeping it running

- **Sleep.** A sleeping Mac stops its agents. On a desktop Mac: System Settings,
  Energy, **Prevent automatic sleeping when the display is off**: on. A laptop
  keeps this only on power.
- **FileVault off.** With FileVault on, a Mac that restarts waits at the
  unlock screen for a password before macOS - and SSH - starts, and macOS does
  not log in automatically, which the agents need (section 5): an unattended
  restart (a power cut, an update) would leave them down until someone types
  the password at the Mac. `bootstrap-target.sh` therefore reports FileVault on
  as UNSUPPORTED. Turning it off is the person's (System Settings, Privacy and
  Security, FileVault), and the disk is then readable by whoever holds the
  Mac.
- **A fixed address.** A Mac whose address changes stops answering `<host>`: a
  DHCP reservation in the router, or the `.local` name, keeps it stable.

## 5. The agents user

On a Mac the agents' daemons run in the session of the account that logs in
automatically: that session is what keeps them running with nobody at the Mac,
as lingering does on Linux. So the agents user is the automatic-login account.

- **With an administrator** - `<user>`, section 1 - the split of `../SKILL.md`'s
  "Two users on the target" applies. `bootstrap-target.sh --install
  --read-back <read-back file> --agents-user <agents-user> --agents-password-file <file>`
  creates a STANDARD account, without administrator rights, with its own group
  for the agents root, `<user>`'s key and Remote Login access, makes it the
  automatic-login account and gives its `~/.bash_profile` the PATH Claude Code
  needs. Its password is the person's choice, handed over like any secret
  (`../SKILL.md` step 4); macOS keeps it for the automatic login. Each agent's
  session and stall watchdog are LaunchDaemons that `<user>` installs
  root:wheel 644 into `/Library/LaunchDaemons`, with `UserName` the agents
  user (`/adding-an-agent` section 5, steps 6 and 7): the agents user can
  neither boot them out nor edit them. Homebrew, its formulas and the
  `python3` the stall watchdog runs are `<user>`'s: an agents user that owned
  them could replace the interpreter of the job that supervises it.
  `../verify-privileges.py` checks all of it, the watchdog's interpreter
  included, and the tmux the watchdog runs with every directory searched
  before it on the job's PATH. That PATH is rendered from where tmux and
  `python3` are, so on a Mac without Homebrew, where the agents user installed
  them in its own `~/.local/bin` (the layout of the fleet's own macOS CI
  runner, `CONTRIBUTING.md` section 9), the check FAILs both: the watched
  agent could replace either. The layout that passes is Homebrew's, installed
  as `<user>`.
  **A LaunchDaemon has no window server and no login Keychain, so these agents
  sign in only with a token or an API key**: `/adding-an-agent` refuses a full
  login for them, and `/agent-revive` switches their accounts by token, never
  through a browser.
- **With no administrator** - an automatic-login account without administrator
  rights - the agents run as that account, their jobs LaunchAgents in its own
  session, which it controls: the install reports them UNPROTECTED, and a full
  login works there.

After the bootstrap the Mac restarts once, so the agents user is the account
logged in (`../SKILL.md` step 4).

## 6. A Mac as the LOCAL machine

The machine the person talks to Claude Code on, driving an AWS, Google Cloud or
Linux target. It needs:

- **Claude Code**: `curl -fsSL https://claude.ai/install.sh | bash`, the
  vendor's native installer (https://code.claude.com/docs/en/setup).
- **git and python3**: Apple's Command Line Tools, `xcode-select --install`.
  Their python3 is 3.9, which `../provision.py` supports; it is tested on 3.9.
- **ssh**: part of macOS.
- **The provider's CLI**, for a cloud target only: the AWS CLI version 2
  (`aws.md` section 1) or the Google Cloud CLI (`gcp.md` section 1). Their
  credentials live where those guides say - `~/.aws/` and `~/.config/gcloud/`
  in the person's home, as on Linux.
