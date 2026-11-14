# Installing `device-emulators`

**There is nothing to install for the skill itself.** `check` is Python 3
standard library plus the fleet's own `lib/fleetlib`, which is why there is no
`requirements.txt` beside this file. What gets installed is the **machine**: a
toolchain per platform, and at least one device to run on.

**No step here is per agent.** The config steps are once per install, and every
other step is once per MACHINE, recorded per host.

Do the shared steps, then only the platforms in `platforms.enabled`. When they
are done, `installation/check` exits `0`.

**Enable only the platforms this machine is supposed to run.** `check` exits
on the worst state across `platforms.enabled`, so a platform left enabled on a
machine that has no SDK for it reports the whole skill as uninstalled and blocks
the platform that works. `ios` is refused outright on a non-macOS host unless
the remote route below is set up.

**Two directories are named below.** `<skill dir>` is this skill's directory
(the directory the skill was loaded from), which holds the COMMON files.
`$CONTEXT` is this skill's install context, which holds the SPECIFIC ones -
`config.json`, `CONTEXT.md` and `installation/.install-state.json`:

```bash
CONTEXT=$(fleet where device-emulators)
mkdir -p "$CONTEXT/installation"
```

---

## Shared: 1. Node, the repo's dependencies, and the build CLI's session

```bash
node -v
npm ci                               # at the repo root
```

...and the same in every other package root the dev stack builds, if it has
any.

The local build declares a logged-in context, so an unauthenticated agent fails
**at the build**, not at a login step. Either route satisfies `check`:

- **CI:** export the token in the variable named by `ci.eas_token_env`.
- **Workstation:** log the CLI in once; the session is stored in the home
  directory.

## Shared: 2. Create `config.json`

```bash
install -m 644 "<skill dir>/config.example.json" "$CONTEXT/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode. Replace every placeholder. The `_comment` keys say what each value is and
how to obtain it; `SKILL.md` *Config keys* is the same list in one table. The
repository paths in it (`build.script`, `build.dev_script`,
`build.env_config_script`, `android.hypervisor_probe`,
`docs.build_machine_components`, `device_e2e.runner`) are relative to the
repository root, the install root holding `.claude/fleet.json`, and each script
they name implements the interface in `SKILL.md` *The two scripts*.

**TWO keys `check` never reads, and they fail differently from every other
key.** `keystore.dir` and `metro.host_cmd` are cited only by prose -
`technical/android.md` section 3b and `technical/ios.md` section 4a - so a name
that has gone out of step with `config.example.json` surfaces as an unresolved
placeholder in a document, never as a failed check. Nothing is installed against
either, which is why changing them does not move `SKILL.md`'s `version`. **Every
key `check` DOES read fails loudly instead, naming itself** - and that set
includes `ios.remote.host`, `ios.remote.user` and `ios.remote.workdir`, which
ARE version-bearing, because they come with an install step (the SSH key and the
directory on the remote Mac).

**Nothing machine-specific goes in it.** The file is committed and an install
is worked from several machines, so a transcribed Xcode version, SDK path or
device list would be wrong everywhere but here while still reading as
authoritative. `config.json` holds CHOICES (the device the team standardises
on); `check` discovers STATE (what this machine actually has). The test: a value
that would still be correct after `git clone` onto a fresh machine is a choice.

**One class of value fails that test and still has to be written down: the
COORDINATES OF ANOTHER MACHINE** - `ios.remote.host` and `ios.remote.user`. They
cannot be discovered, because discovering them is the very thing they are needed
for, and no probe can ask a machine it cannot yet address. **The form is the
answer, not an exemption**: they are written `${VAR:-default}`, so the committed
text is the team's standing choice and any machine or person overrides it
through the environment WITHOUT editing a file everyone shares. Read the rule
as: a bare literal that a fresh clone would get wrong does not belong here; an
overridable default does. `keystore.dir` has the same shape for the same reason,
under `FLEET_SECRETS_DIR` because it names a credential directory.

Two that are easy to get wrong:

- **`android.avd.default`** must be a name `emulator -list-avds` prints, not the
  friendly name Android Studio's Device Manager shows. A wrong value is caught
  here in a second; uncaught, it is discovered about twenty minutes into a
  Gradle run.
- **`ios.device_type_id`** must be a real device-type identifier
  (`xcrun simctl list devicetypes`). A display name here fails only on a machine
  that had no device - which is the CI agent, not the one you tested on.

Then write `$CONTEXT/CONTEXT.md`: which project and machines, what the install's
scripts add to the interface (their timeout knobs, failure messages and the
functions behind each step), what its dev script leaves behind after a cgroup
stop and what its `down` prints, which credential channel the remote route
uses, and what is not ruled. Nothing enforces it, which is exactly why it is
written by hand - a wrong value there fails silently as bad judgement rather
than loudly as an error.

---

## iOS: 1. Xcode, selected and licensed

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
sudo xcodebuild -runFirstLaunch
xcodebuild -version                  # must exit 0
```

**An unaccepted licence fails every build with a licence error, not a build
error**, which is why `check` runs `xcodebuild -version` rather than looking for
the app bundle. On CI the two `sudo` lines are the unattended equivalents of the
first-launch dialogs a human clicks through once.

## iOS: 2. An iOS runtime

```bash
xcodebuild -downloadPlatform iOS
xcrun simctl runtime list            # expect at least one (Ready)
```

**Xcode images ship with no iOS runtime.** This is the single most common
reason a CI agent with Xcode installed cannot run a simulator, and it presents
as "no available iPhone simulator" rather than as a missing runtime.

## iOS: 3. A device, and CocoaPods

```bash
xcrun simctl list devices available | grep iPhone || \
  xcrun simctl create "<ios.device_type>" "<ios.device_type_id>"
brew install cocoapods               # the prebuild runs pod install
```

`simctl create` takes the device-type **identifier**, not the display name
`simctl list devices` shows. `xcrun simctl list devicetypes` maps one to the
other.

---

## iOS, REMOTE ROUTE ONLY: the operator's machine is not a Mac

**Skip this on a Mac.** It is the install for `technical/ios.md` section 4a:
Metro and the backend stack on the operator's own host, the build and the
simulator on a Mac over SSH. The iOS steps above are then done **on the Mac**,
not here.

Set `ios.remote.host`, `ios.remote.user` and `ios.remote.workdir` in
`config.json`, and `metro.host_cmd`. Then, from the operator's machine:

```bash
ssh-copy-id <ios.remote.user>@<ios.remote.host>     # key auth, once
ssh -o BatchMode=yes <ios.remote.user>@<ios.remote.host> true; echo $?   # must print 0
ssh <ios.remote.user>@<ios.remote.host> 'mkdir -p <ios.remote.workdir>'
```

**`ios.remote.workdir` must be outside every CI runner's work tree.** A
runner may check out over its own directories at any moment.

`python3 "<skill dir>/installation/check" ios` then proves the SSH leg, the
remote Xcode and the remote device list in one round trip, from this machine.
**It does not prove that the remote can authenticate the BUILD**, and it says
so in its own output line; that is `technical/ios.md` section 4a.1 step 5, done
by hand once, and which credential channel this install uses is recorded in
`CONTEXT.md`.

---

## Android: 1. The SDK

Three binaries have to exist: **`adb`** (platform-tools), **`emulator`**
(emulator) and **`aapt2`** (build-tools, which the build script uses to read an
APK's application id before installing it). The usual route is Android Studio's
SDK Manager, which puts them under the platform default; on CI, `sdkmanager`.

**Do not verify this with `command -v adb` in your terminal.**
`technical/android.md` section 1 has the reason in full: an rc file is read by
interactive shells only, so a PATH check passes for you and fails for every
non-interactive caller with the same SDK installed. `check` resolves the
binaries the way the build script must, which is the only oracle that matches
what a build will actually see.

If the SDK is not under a platform default, export `ANDROID_HOME` for the
sessions that need it rather than editing an rc file:

```bash
export ANDROID_HOME=/path/to/sdk
```

## Android: 2. A usable hypervisor

An AVD is a directory; booting one needs a hypervisor under it. On Linux that is
KVM, and both ways it can be missing leave `emulator -list-avds` looking
perfectly healthy.

```bash
emulator -accel-check     # must exit 0
```

The legs live in the repository's probe (`android.hypervisor_probe`, interface
in `SKILL.md` *The two scripts*), which `check` imports. On Linux it names the
two causes it can identify precisely, and hands the rest to `-accel-check`,
which is why it runs all three legs rather than the two:

- **`/dev/kvm` does not exist** - the module is not loaded, virtualization is off
  in firmware, or this machine is a guest whose host has not enabled nested
  virtualization. A machine ADMIN loads it: `sudo modprobe kvm_intel` (`kvm_amd`
  on AMD).
- **`/dev/kvm` exists and this user cannot open it** - the device is owned by a
  group this user is not in, which is the state a fresh account is in. A machine
  ADMIN grants it:

```bash
sudo usermod -aG kvm "$USER"
sudo systemctl restart <the unit running the session>   # or log out and back in
```

**A process that is already running does not pick up a new group**, so the
restart is part of the fix rather than a formality - `usermod` alone leaves
`check` red and the AVD unbootable. None of this is the operator's or an agent's
to perform: it is machine configuration.

A non-zero `-accel-check` that is neither of those is a real third case -
another hypervisor holding the device, a kernel/userspace mismatch, nested
virtualization refused by the host - and the probe reports the emulator's own
words for it rather than guessing.

On macOS the accelerator is HVF and there is no `/dev/kvm`. A probe that does
not measure macOS says so ("not probed on darwin"), and `check` prints those
words in its line; running `emulator -accel-check` there by hand and recording
the result is what lets the probe cover that platform too.

## Android: 3. A JDK

The `emulator` binary needs none; a Gradle build does. The floor is
`android.jdk_min_major` and `check` enforces it, on `javac` and never on `java`.
The full pinned combination a build machine needs is in the document
`config.json` names as `docs.build_machine_components`.

## Android: 4. At least one AVD

In Android Studio's Device Manager, or with `avdmanager` on a CI agent. Then
confirm the name the emulator itself uses, which is not always what the Device
Manager displays:

```bash
emulator -list-avds
```

## Optional: the device-e2e tap driver

Only if this machine runs the install's device e2e suite. **The operator loop
does not need it**, and `check` reports its absence without failing - a machine
that only builds and runs dev builds is fully installed without it. For Maestro:

```bash
curl -Ls https://get.maestro.mobile.dev | bash
~/.maestro/bin/maestro --version
```

It needs a JVM, which the Android toolchain above already requires.

**The installer appends its bin directory to `~/.zshrc` and
`~/.bash_profile`** - rc files, read by INTERACTIVE shells only. Every
non-interactive caller (CI, a git hook, an agent's tool shell, cron) will
therefore have a working install and no `maestro` on PATH, which is why `check`
tries `device_e2e.driver_path` **before** PATH and names the tool as
`device_e2e.driver`, and why a runner should do the same. Do not "fix" this by
adding it to a profile a non-interactive shell still will not read.

---

## Last: record the install for THIS machine

`check` compares this record against the `version` in `SKILL.md`. Without it, an
install cannot be told from a stale one, so `check` reports stale.

**The record is keyed by hostname, and this step MERGES into it.** A single
host field would make every other machine report stale, and re-recording it
would un-record the machine before it - so two machines could never both be
installed. The step below adds or replaces only this machine's entry and leaves
the others alone. Run it once per machine.

```bash
python3 -c '
import json, re, socket, sys, time, pathlib
skill, state = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
v = int(re.search(r"^version:\s*(\d+)$", (skill / "SKILL.md").read_text(), re.M).group(1))
data = json.loads(state.read_text()) if state.exists() else {}
data.setdefault("versions", {})[socket.gethostname()] = {
    "version": v, "by": "INSTRUCTION.md",
    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
print("recorded version", v, "for", socket.gethostname())
' "<skill dir>" "$CONTEXT/installation/.install-state.json"

python3 "<skill dir>/installation/check"     # expect: OK: installed and current (version N) on <host> - ...
```

**Do this only after `check` has stopped exiting `2`.** The record says the
machine tests passed; writing it first records nothing and turns a check that
reads real artifacts into a marker file that lies.

---

## Run `check` until it exits 0

```bash
python3 "<skill dir>/installation/check"          # every platform in platforms.enabled
python3 "<skill dir>/installation/check" ios      # or just one
```

| Exit | Means | Do |
|---|---|---|
| `0` | installed and current | proceed |
| `1` | no record for this machine, one against an older `version`, or NO VERDICT (no install context resolved) | re-read this file from the top, then redo the last step; for NO VERDICT, run it from the install or set `FLEET_CONTEXT_ROOT` |
| `2` | not installed: the line names which artifact is missing, per platform | fix that one thing, run it again |

`check` is also this skill's **only** machine inventory: its `0` line prints the
versions, runtimes and AVDs this machine actually has. Nothing transcribes that
anywhere, because a copy can only go stale.

## Verifying the scripts themselves

```bash
python3 "<skill dir>/installation/check.test.py"   # offline, against the fleet's fixture install
node "<skill dir>/config.test.mjs"                 # the install's config.json against the example
python3 "<skill dir>/luma.test.py"                 # offline, generates its own PNGs
```

`check.test.py` builds throwaway installs and fake tools in a temporary
directory and never touches a real SDK, device or Mac; every state `check`
reports has a case that produces it. `config.test.mjs` reads the install's
`config.json` through `fleet where device-emulators config.json` (or
`DEVICE_EMULATORS_CONFIG`), so running it from the install checks the install's
own copy.

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than this machine's
record. Re-read this file from the top: a bump means something here changed, and
the only way to know what is to walk it. Then redo the last step.

The converse does not hold, and it is worth stating because the absence of a
bump looks like the absence of a change: **a step `check` can detect on its own
does not move `version`.** The version exists for the steps whose omission is
silent. A step whose omission makes `check` exit `2` with the cause named needs
no flag in a state file, and bumping for it would report every correctly
installed machine as stale over something the check would have told them.
