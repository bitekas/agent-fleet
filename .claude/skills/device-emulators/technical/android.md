# Android AVD: prerequisites and loops

Values come from the install's `config.json`; `<key>` below means substitute it.

**Sections 3a and 3b run through the build script**, in the grammar `SKILL.md`
*The two scripts* declares. **Everything else is stock platform tooling** and
holds on any machine. An install whose build script takes other arguments
writes its own forms of those two sections' commands in its `CONTEXT.md`, which
outranks the blocks here; the rest of each section still applies. It is stated
here as well as in `SKILL.md` because this is the file an operator copies
commands from, and a command block that opens with `<build.script>` looks
portable until you read the flags after it.
Every step is marked VERIFIED (proven, with what proved it) or UNVERIFIED
(written from the build script's documented behaviour or from general Android
knowledge, not run). **Running an unverified step means updating its marker,
as a change to this file in the fleet repository** - that is how this file
stops being part placeholder.

The emulator loop is driven end to end by the build script, which boots the AVD,
waits for a completed boot, installs, launches and deep-links the dev client at
Metro. **This file does not reimplement any of that.**

## 1. Prerequisites

| Needs | Prove it | Why |
|---|---|---|
| `adb` (platform-tools) | see the resolution order below | install, launch, logcat, screenshot |
| `emulator` (emulator) | same | boots the AVD |
| `aapt2` (build-tools) | same | reads an APK's application id; the build script refuses an install it cannot check |
| A usable hypervisor | `emulator -accel-check` (exit 0) | an AVD that exists still needs something to run on |
| A JDK >= `android.jdk_min_major` | `javac` present, `java -version` | the Gradle build needs one; the emulator does not |
| >= 1 AVD | `emulator -list-avds` | the one argument the build script cannot guess |

`installation/check` asserts all of it in one command and one line.

### How the SDK is found, and why PATH is not the oracle

`installation/check` resolves each binary in this order, and the build script
must resolve it in the same order. Each lookup returns an absolute path, so no
later call can silently pick a different binary:

1. `PATH` - an operator who overrode it meant to
2. `$ANDROID_HOME`
3. `$ANDROID_SDK_ROOT`
4. `~/Library/Android/sdk` (macOS default)
5. `~/Android/Sdk` (Linux default)

...each searched under `platform-tools/`, `emulator/`, `cmdline-tools/latest/bin/`,
then the newest `build-tools/<version>/`.

> **Do not reduce this to a PATH check.** `adb` and `emulator` reach a
> developer's PATH from their shell rc, and **an rc file is read by interactive
> shells only**. Every non-interactive caller - a CI step, a git hook, an
> agent's tool shell, `sh -c`, cron - sees a PATH with no Android SDK on it.
> Measured: `command -v adb` succeeds in an interactive terminal and fails in a
> non-interactive shell on the same machine **with the same SDK installed**. A
> PATH-only check tells a reader with a complete SDK to go install one.
> A check that reports a state the build script disagrees with is worse than no
> check, which is why the two orders are kept identical.

### "An AVD exists" and "an AVD boots" are different facts

`emulator -list-avds` reports the first and is silent about the second: it lists
an AVD that cannot start exactly as it lists one that can. On Linux an AVD boots
only if `/dev/kvm` exists and this user can **open** it read-write, and
membership of the device's group is what grants that. Both fixes are machine
configuration a machine ADMIN performs - loading the module, or
`sudo usermod -aG kvm <user>` - and **a process that is already running does
not pick up a new group**, so the session restarts or the user logs out and back
in before it takes. On macOS the emulator accelerates through HVF and there is
no `/dev/kvm`; `-accel-check` is the check that matters on every platform.

Those three legs - the node exists, a real `open()` succeeds, `-accel-check`
exits 0 - live in ONE place, the repository script `android.hypervisor_probe`
names. `installation/check` imports it, and the build script invokes it when an
AVD fails to attach so that its die message names the right remedy; a second
copy in either consumer is the bug that split exists to prevent. Either way the
line names the cause instead of the symptom. It opens the device rather than
testing its permission bits because only the open goes through the
device-cgroup controller, the LSM policy and the driver, and because a bit test
is unconditionally true for `root`, which is what a CI agent runs as.

Run it directly to ask this machine the question:
`python3 <android.hypervisor_probe> probe`. **Three exit states, and the third
is not a pass**: `0` the accelerator is usable, `1` a named cause with the admin
command, `2` not measured here (a platform the probe does not measure, or a leg
that could not run).

### The BUILD needs more than the emulator does: `ANDROID_HOME` and a JDK

The resolution order above gets `adb` and `emulator` for the check and the
build script. Gradle is a different process and reads the environment, so the
build additionally needs `ANDROID_HOME` exported and a `JAVA_HOME` pointing at a
**JDK** - and in a non-interactive shell neither is set, for the same rc-file
reason.

`<build.script>` derives and exports both before Gradle starts, and refuses with
a named remediation when it cannot. What it prevents is two errors that arrive
late and accuse the wrong thing:

| Missing | What Gradle says, minutes in |
|---|---|
| `ANDROID_HOME` | `SDK location not found. Define a valid SDK location with an ANDROID_HOME environment variable...` - while the build script has already resolved the SDK for `adb` |
| a JDK | `Toolchain ... does not provide the required capabilities: [JAVA_COMPILER]` |

**`java` on PATH is not the precondition; `javac` is.** A machine whose
default runtime is a **JRE** answers `java -version` perfectly and cannot
compile, so every "is there a java?" check passes and the build still dies. The
JDK floor is `<android.jdk_min_major>`, the same number `installation/check`
enforces, and a machine that check calls ready is one the build accepts.

**An explicitly exported `JAVA_HOME` is REFUSED rather than replaced** when it
is a JRE or below the floor. An operator who exported one meant it; silently
building against a different JDK and saying nothing is worse than stopping.

If the SDK is elsewhere, point at it per invocation rather than editing an rc
file that non-interactive shells will not read anyway:

```bash
ANDROID_HOME=/path/to/sdk <build.script> android --env <build.default_env> \
  --method <build.method_metro> --emulator <android.avd.default>
```

### Why the AVD list comes from `emulator`, not `avdmanager`

`emulator -list-avds` needs no JDK. `avdmanager` is a Java tool, so on a machine
with the SDK and no JDK the avdmanager route turns *"you typed the wrong AVD
name"* into a stack trace about `JAVA_HOME`.

An unknown `--emulator <avd>` dies **before the build**, listing the AVDs that
do exist - so a typo costs a second rather than a ~20-minute Gradle run. Create
AVDs in Android Studio's Device Manager, and use the name `emulator -list-avds`
prints, not the friendly name the Device Manager displays.

**"Installed" is per-AVD.** Each AVD has its own data partition, so a build
installed on `android.avd.default` is absent from `android.avd.compat`, and
`--no-build` on the second one correctly dies naming the build invocation.

### Timeouts, when the machine is slow

The build script bounds every wait - AVD start to adb attach, attach to
`sys.boot_completed=1`, the package manager resolving the launcher activity, the
launch to the dev launcher recording a load of this Metro, the re-check for an
already-running AVD before booting one, and how long a dead emulator pid is
tolerated before the failure is called a process death - each by an environment
variable with a default. The install's `CONTEXT.md` names them and their
defaults. All are generous on purpose - a tight bound buys nothing on the happy
path and manufactures failures under load. Raise them by environment variable;
do not edit the defaults.

What the bounds are sized on, measured:

- **The dev launcher's registry entry** is written only once the bundle has RUN
  (~9 s after the manifest fetch on a warm Metro), so the load bound is sized
  for a cold Metro's first bundle build.
- **The process-death grace** is sized on ATTACH (seconds), not on a completed
  boot (tens of seconds): what has to happen inside it is `adb` seeing the
  device, not Android finishing.
- **Cold-boot times** on one machine, same AVD: **30s and 62s**. A snapshot
  restore comes up boot-complete in ~1s and exercises none of the boot path, so
  anyone re-measuring must force a cold boot (`-no-snapshot-load`) or they will
  measure nothing.

**The attach bound is the knob for a machine that is SLOW, and it is the wrong
one for a machine whose AVDs cannot boot at all.** Raising a bound on something
that will never happen only makes the same failure take longer. So the build
script does not offer it unconditionally: on a failed attach it probes the
hypervisor first and prints the matching remedy - the admin command when the
accelerator is the problem (and, in those words, *do not* raise the timeout), the
timeout knob when the accelerator is fine, and both when it could not measure.

### Headless when there is no display, and it is not optional

The emulator is a Qt application. On a **display-less** host - every CI runner,
every agent's tool shell, every SSH session with no X forwarding - a windowed
boot dies on the Qt platform plugin in a second or two and never attaches to adb.

`<build.script>` boots with `-no-window -gpu swiftshader_indirect` **on Linux
when `$DISPLAY` and `$WAYLAND_DISPLAY` are both empty**, and windowed otherwise.
VERIFIED 2026-09-09 on a Linux host: headless reaches `sys.boot_completed=1`
normally (21s, cold), windowed under the same environment does not start at
all.

**THE AUTOMATIC RULE IS LINUX-ONLY, AND ON macOS IT WOULD BE BACKWARDS.**
macOS has shipped no X11 since 10.8: `DISPLAY` is unset on a normal GUI Mac
(XQuartz sets it only for shells started after it launches) and
`WAYLAND_DISPLAY` never exists there - so the same test would call a Mac with a
perfectly good display "display-less" and hand every `--target simulator` run a
window nobody can see.

**The test is PRESENCE, not usability, so there is a knob** that forces headless
or windowed on every platform (the install's `CONTEXT.md` names it). Force
headless when a Linux shell inherits `$DISPLAY` from a desktop session that is
dead or unreachable (an agent's tool shell forked from one is the everyday
case): that run otherwise takes the windowed branch and reproduces the original
failure. Force windowed on macOS, or on a host running an X server this test
cannot see.

**`-gpu swiftshader_indirect` travels with `-no-window`**: with no display
there is no host GL to accelerate against, and the default `auto` picks a backend
with no surface to draw on.

### A dead emulator and a slow one are different failures

When an AVD fails to attach, the reason is in the log the build script names on
the way past: `${TMPDIR:-/tmp}/<project.artifact_prefix>-emulator-<avd>.log`.

**Read WHICH failure the message reports before reaching for the attach
timeout.** The build script distinguishes them, and they have opposite remedies
(the install's `CONTEXT.md` quotes its exact messages):

- **The emulator process is GONE** some seconds after launch. Raising the bound
  makes the identical failure take longer. The message quotes the first error
  line from the log; a Qt platform-plugin line there means the AVD was booted
  WINDOWED with no usable display, which has three causes: the headless knob
  forcing windowed, a `$DISPLAY` / `$WAYLAND_DISPLAY` that is set but dead, or a
  non-Linux host where the automatic rule does not apply.
- **The AVD did not attach to adb within the bound**, with no mention of the
  process having exited - the emulator is still up, so this is a genuinely slow
  boot and the timeout knob is the right one. Which of the two remedies that
  message then offers depends on what the hypervisor probe says about this
  machine.

The process-death verdict waits its own grace after the launcher pid exits
before pronouncing, because a launcher that re-execs or daemonises leaves that
pid dead while the AVD comes up fine. Its own knob, not the attach grace: one
name for both would make an operator who raised it for a forking launcher also
make every boot wait that long before starting an AVD.

The seconds in that message are counted from LAUNCH to the verdict, not from
the process's death - nothing records when the process died, and the death is
noticed up to one grace window after it happens. Do not read it as a lifetime
when correlating against timestamps in the log.

## 2. A fresh CI agent

UNVERIFIED as a sequence.

- **Install the SDK's `platform-tools`, `emulator` and `build-tools` packages**,
  plus a system image, with `sdkmanager`. Export `ANDROID_HOME` for the job rather than
  editing an rc file (section 1).
- **Create an AVD**, because images ship with none:
  `avdmanager create avd -n <android.avd.default> -k "<system image>"`. This is
  the one place `avdmanager` is worth its JDK dependency, since a CI agent that
  builds has a JDK anyway.
- **A JDK >= `android.jdk_min_major`.** The pinned combination a build machine
  needs is in `docs.build_machine_components`; `check` enforces only the floor.
- **Hardware acceleration decides whether the agent is usable at all**, and it
  is not a budgeting question. `installation/check` REFUSES a Linux machine
  whose `emulator -accel-check` is non-zero - a virtualized runner needs nested
  virtualization from its host, and the `kvm` group membership on the runner's
  own account. Both are machine configuration an ADMIN performs when the agent
  is provisioned, so provision them with the SDK rather than discovering them at
  the first boot timeout.
- **Export the variable `ci.eas_token_env` names** - nothing else authenticates
  a non-interactive agent, and the local build declares a logged-in context.

## 3. The loops

**Ports and host first.** Both come from the running stack, never from a
document: the host from the dev script's banner, the Metro port from
`build.ports_artifact` under key `build.metro_port_key`.

### 3a. `--method <build.method_metro>`: the emulator loop

`--emulator <avd>` is Android-only and **implies `--target simulator`**. One
command builds, boots the AVD if it is down, waits for a completed boot,
installs, and launches the dev client with ONE intent that names Metro, then
waits for the launcher to record that load (the pointing note below).

```bash
<build.dev_script> up <build.dev_client_service> --env <build.default_env>

<build.script> android --env <build.default_env> \
  --method <build.method_metro> --emulator <android.avd.default>
```

VERIFIED - the canonical emulator workflow; the build script's emulator path
carries per-step measurements.

**Iterate without rebuilding** - seconds, not ~20 minutes. No Gradle, no signing
key materialized, no artifact read. A JS-only change needs nothing at all
(`technical/hot-reload.md`); this is for when the app itself must be relaunched:

```bash
<build.script> android --env <build.default_env> \
  --method <build.method_metro> --emulator <android.avd.default> --no-build
```

VERIFIED. `--no-build` **dies rather than falling back to a build** when
the app is not on that AVD; it installs nothing, so it is never the retry for a
failed install - it would report success over the *old* build.

| Want | Command |
|---|---|
| the single running emulator, no AVD named | `<build.script> android --env <build.default_env> --method <build.method_metro> --target simulator` |
| compat pass on another AVD, reusing its installed build | `... --emulator <android.avd.compat> --no-build` |
| the routing without building anything | append `--dry-run` |

With no `--emulator`, `--target simulator` dies on **zero or several**
emulators rather than guessing - picking the first would install onto and launch
on whichever attached first, while every message on screen still read
"installed on emulator".

**Pointing the client at YOUR Metro, and proving it took.** Every route above
goes through the build script, whose launch IS the dev-client URL and which then
waits for the launcher's registry to record a load of that Metro. Any route that
does NOT - tapping the icon, a hand-rolled launch - is a plain launch, and a
plain launch loads the LAST-OPENED bundle, which on a box running several serves
is often another worktree's (`SKILL.md` trap 9). By hand: force-stop, then ONE
intent carrying the URL, with the `url=` value URL-encoded, the port read from
the running stack's port artifact, and `$SCHEME`/`$PKG` taken from `--dry-run`'s
`scheme=`/`identity=` rather than hardcoded (`SKILL.md` trap 3):

```bash
adb -s <serial> shell am force-stop "$PKG"
adb -s <serial> shell am start -a android.intent.action.VIEW \
  -d "\"$SCHEME://expo-development-client/?url=http%3A%2F%2F<host>%3A<port>\"" \
  -n "$PKG/.MainActivity"    # the launcher activity: resolve it, as the build script does
```

**ONE intent, never a plain `am start -n` first.** MEASURED 2026-09-23 on an
API 36 AVD, 5 of 5 cold launches, counting the launcher's manifest fetches at a
logging proxy in front of each serve: `am start -n <activity>` carries no
action, so the dev launcher takes neither its deep-link branch (no data) nor its
last-opened branch (which requires `ACTION_MAIN`) and stops on the LAUNCHER
SCREEN; the deep link sent after it is *"delivered to currently running
top-most instance"* and loads nothing either. Zero fetches on the target, zero
on the last-opened serve, a live pid, and the registry unchanged. The single
cold VIEW intent above made exactly one fetch, on the target, 5 of 5. The dev
launcher (57.0.20) has no URL intent extra; the intent's data URI is the
interface, and on a cold process its branch loads that URL and returns before
the last-opened and default-URL branches. `force-stop` is what keeps it cold:
the launcher silently DROPS a load requested while another is still in flight
(`appIsLoading`), so an intent that lands on a process mid-load can be lost.
Android has no concurrent double load of the iOS kind for the same reason.

Do this before **every** capture and **every** test run rather than once per
session: it makes your serve the launcher's most recent entry only until anyone
else on the box opens theirs.

`am start` exits 0 for launches that did not happen (`SKILL.md` trap 5) and the
launcher falls back to the launcher screen or to the previous entry when the
serve is slow to answer, so read the launcher's own recently-opened registry
back. The entry with the newest `timestamp` is what the client took, and its
`url` names the port. It is written when the load COMPLETES - measured ~9 s
after the manifest fetch, 2026-09-23 - so poll it for an entry newer than the one
there before the launch, rather than reading it once:

```bash
adb -s <serial> shell run-as "$PKG" cat shared_prefs/expo.modules.devlauncher.recentyopenedapps.xml
```

The misspelling in that filename is the launcher's, not a typo here. Android
drops entries older than three days, so an empty registry means "nothing opened
recently", not "nothing opened".

Two other instruments corroborate it, and neither is redundant - the registry
says which serve the client ASKED for, these say what it is running. **Metro's
own output**: its bundle line and the app's `LOG` lines travel the Metro
websocket, so they cannot appear on a machine the app is not attached to. And a
**bundle marker only the intended serve carries** - a testID or string the
branch introduces, measured ABSENT from every other serve on the box - observed
in the running client.

**A SCREEN deep link (`$SCHEME:///<route>`) is neither of these**: it opens
that route in whatever bundle is already loaded, so it can never re-point one
(`SKILL.md` trap 9).

**What can go wrong, and what it is not**

- **Do not "fix" a launch with `monkey -p <pkg> -c android.intent.category.LAUNCHER 1`.**
  It is the recipe every search result gives and it does not work here:
  measured on an API 36 AVD, monkey exits **-5 having started nothing**. Ask the
  device instead (`cmd package resolve-activity --brief`), as the build script
  does.
- **Do not hardcode `.MainActivity`.** It is the generated default today and
  is a fact about the *generated* manifest: a prebuild, a plugin or a config
  change moves it, and the failure looks like a broken installed build.
- A deep link refused with a scheme mismatch means the build was made for a
  different `--env`/`--method` pair. Identity comes from (env x method); ask
  `<build.env_config_script>`'s `env_config`, or read `--dry-run`'s `identity=`
  and `scheme=`. Never hardcode one.
- **A re-install KEEPS THE APP'S DATA, AND THE IMAGE CACHE IS DATA.**
  `adb install -r` - which is what the install step does, and the only thing that
  makes re-installing over a running build possible at all - replaces the APK and
  keeps `/data/data/<identity>` untouched. So an image cache survives every
  re-install and every rebuild.
  **The trap: reusing a previous pass's photo URL with new bytes behind it
  renders the OLD image, with NO request on the wire.** There is nothing to see
  in Metro, nothing in logcat, and no failed fetch - the screen simply shows last
  pass's picture, which reads as the app ignoring the fixture or as a backend
  serving stale data. Two ways out, and pick by what the run needs:
  serve each pass's bytes under a **new filename** (cheap, keeps the install), or
  `adb -s <serial> uninstall <identity>` first (thorough, and it also drops the
  saved Metro URL, so the dev client comes back on its launcher screen).

### 3b. `--method <build.method_embedded>`: build an APK, sideload it, launch it

**`--emulator` and `--target simulator` are not available for
`--method <build.method_embedded>`.** The build script rejects
`--target simulator` with any method but `<build.method_metro>`, because a
simulator build loads its JS from Metro, and `--emulator` implies
`--target simulator`.
An embedded build onto an emulator is therefore a **manual sideload**.

VERIFIED 2026-09-02 - both refusals reproduced with `--dry-run`. The build in
the first step below is likewise VERIFIED by `--dry-run`; the remaining steps
are UNVERIFIED as a sequence: nothing here has been run against a live AVD.

```bash
# 1. build the APK to disk
<build.script> android --env <build.default_env> \
  --method <build.method_embedded> --sign sideload --target file
```

Artifact: `<android.apk_artifact>` **at the root of the checkout you ran it
from** - a worktree's build lands in that worktree, not in the main checkout.
(`--sign release` emits an **AAB**, `<android.aab_artifact>`, which cannot be
sideloaded; `--target file` is the only destination an embedded build has that
leaves the artifact alone.)

The build script dies rather than carry on when the build did not rewrite that
file during this run (`SKILL.md` *The two scripts*; a local-build override
variable left in the shell is the measured cause: the build tool then exits 0
and writes nothing, and the script names the variable), so the file there after
a successful run is this run's. Its own emulator and device installs also
refuse an APK whose application id (read with `aapt2`) is not the build's; the
manual `adb install` below has no such check.

> **The shared non-store key this build signs with lives outside the checkout**,
> at `<keystore.dir>/shared/`. One location per machine, so every worktree and
> every clone resolves the same key and a signed build needs no per-worktree
> setup.
>
> **`--dry-run` proves nothing about that key.** It prints the key path
> without reading it, so a green dry run says the path was computed, never that
> the file exists or is readable. Only a real signed build exercises that, and a
> missing key then fails at the signing step, after the whole build.

```bash
# 2. boot the AVD and get its serial
emulator -avd <android.avd.default> &      # skip if it is already up
adb devices                                # -> emulator-5554
adb -s emulator-5554 emu avd name          # which AVD that serial actually is
```

**Use `-s <serial>`, never `adb -e`.** `-e` means "the one and only emulator"
and refuses outright ("more than one device/emulator") the moment a second AVD
is running - which is the normal state of this workflow.

**Wait for a completed boot before installing.** `adb wait-for-device` does
**not** close the window: measured, it returns ~26 seconds before the system is
usable, and an install inside that window dies with `Error: device is still
booting`, throwing away the build that came before it.

```bash
until [ "$(adb -s emulator-5554 shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; do sleep 3; done

# 3. sideload
adb -s emulator-5554 install -r <android.apk_artifact>

# 4. launch, resolving the launcher activity from the device
PKG=$(bash -c 'source <build.env_config_script>; env_config <build.default_env> app_identifier')
COMP=$(adb -s emulator-5554 shell cmd package resolve-activity --brief \
         -c android.intent.category.LAUNCHER "$PKG" | tr -d '\r' | tail -1)
adb -s emulator-5554 shell am start -n "$COMP"
adb -s emulator-5554 shell pidof "$PKG"    # positive evidence it stayed up
```

**This route is the one place a plain `am start` is the whole answer**
(`SKILL.md` trap 9 does not apply here): an embedded build carries its own JS and
runs no dev launcher, so there is no bundle to point anywhere and no
recently-opened registry to read. That is also why its identity is
`app_identifier` and not the dev client's (`--dry-run`'s `identity=` on a
`<build.method_metro>` build) - it is a different app from the dev client.

(The build script does the boot gate for you on every `--target simulator` path.
The block above is the hand-rolled equivalent for the sideload route, which has
no such path.)

**`am start`'s exit status is not an oracle** - it is 0 for launches that did
not happen, printing `Error: Activity not started` onto stdout while the shell
reports success. The `pidof` check is the evidence; a crash-on-launch shows up in
`adb -s emulator-5554 logcat -d -t 200`.

`resolve-activity` can return nothing usable for a short window *after*
`sys.boot_completed=1`: an intermittent boundary transient, not a fixed lag.
Poll it rather than concluding the app is not installed.

**Embedded and Metro builds side by side:** they wear **different application
ids**, so both install at once and neither overwrites the other. Ask
`env_config` or `--dry-run`; never hardcode an id.

## 4. Input: taps, swipes, keys, text

Android **can** be driven headlessly, and this is the asymmetry with iOS worth
knowing before designing a job around either: `adb shell input` needs no
permission, no extra tool and no window.

```bash
adb -s emulator-5554 shell input tap <x> <y>
adb -s emulator-5554 shell input swipe <x1> <y1> <x2> <y2> [<ms>]
adb -s emulator-5554 shell input keyevent KEYCODE_BACK      # or HOME, ENTER, ...
adb -s emulator-5554 shell input text 'hello'               # into the focused field
```

VERIFIED 2026-09-03 on an API 36 AVD: `input tap 540 700` inside the Settings
list moved the focused window from `SettingsHomepageActivity` to `SubSettings`,
and the screenshot changed; `input keyevent KEYCODE_BACK` moved it back. Both
exit 0.

**Coordinates are DEVICE pixels, and they are not portable across AVDs.** A
tap written against one screen size lands somewhere else on another. Read the
size rather than assuming it:

```bash
adb -s emulator-5554 shell wm size          # -> Physical size: 1080x2400
```

**A display override turns one AVD into a different phone**, which is how an
install's visual sweep gets a short phone out of `android.avd.default`:
`wm size` takes `android.sweep_short_screen.size` (device pixels, WxH) and
`wm density` takes `android.sweep_short_screen.density` (dpi), and the screen
drawn is size x 160 / density, in dp. The override belongs to the emulator, not
to the app, so the pass ends with `wm size reset` and `wm density reset`, and
`wm size` printing no `Override size` line is the proof it is gone.

```bash
adb -s emulator-5554 shell wm size <android.sweep_short_screen.size>
adb -s emulator-5554 shell wm density <android.sweep_short_screen.density>
# ... the pass ...
adb -s emulator-5554 shell wm size reset
adb -s emulator-5554 shell wm density reset
```

**`input` has no idea whether anything received the tap.** It reports success
for a tap into empty space, so the exit code is not an oracle here either
(`SKILL.md` trap 5). Assert on the *consequence* - the focused window, or a
screenshot that differs:

```bash
adb -s emulator-5554 shell dumpsys window | grep -m1 mCurrentFocus
```

**`input text` cannot type into an unfocused field, and it mangles some
characters** (spaces need `%s` or quoting, and punctuation varies by IME). For
anything longer than a word, prefer setting the value through the app under
test rather than typing it.

## 5. Screenshot

```bash
adb -s emulator-5554 exec-out screencap -p > /tmp/<project.artifact_prefix>-emulator.png
```

VERIFIED. A build script can print this exact line, with the resolved `adb`
path and serial, at the end of every successful emulator run, so the operator
copies it rather than composing it.

For presenting UI work an ad-hoc emulator screenshot is **not** the gate: the
install's UI evidence gate, where it has one, owns the capture list and the
pack, and the install's `CONTEXT.md` names it. Whether an emulator capture
satisfies that gate at all is the install's ruling, and `CONTEXT.md` records it
or records that it is open.

## 6. Record a video

Three routes. All three were measured on an API 36 AVD on 2026-09-03 and **all
three produced a finalized, playable file** (`ftyp` and a `moov` index present).

```bash
# A. self-terminating - the one to use in a non-interactive job
adb -s emulator-5554 shell screenrecord --time-limit 3 /sdcard/rec.mp4
adb -s emulator-5554 pull /sdcard/rec.mp4 /tmp/rec.mp4
adb -s emulator-5554 shell rm /sdcard/rec.mp4
```

VERIFIED - exits 0 on its own, no signal to send, nothing to time. **Prefer
it**: it is the only route with no race in it.

```bash
# B. stop it yourself
adb -s emulator-5554 shell screenrecord /sdcard/rec.mp4 & REC=$!
sleep 5; kill -INT $REC; wait $REC
sleep 2                       # <- see the warning below
adb -s emulator-5554 pull /sdcard/rec.mp4 /tmp/rec.mp4
```

VERIFIED with `SIGINT`, and also with `SIGKILL`. **The signal is not the
hazard.** Killing the *adb client* leaves the on-device `screenrecord` to notice
its output has gone and finalize the file itself, which it did in both cases.

> **The hazard is PULLING TOO EARLY.** The finalize happens on the device
> *after* the client is gone, so a `pull` issued immediately gets a file that is
> still being written - and a half-written MP4 looks like a failed *run* rather
> than a failed *stop*. Wait, or use route A and have no window to get wrong.

```bash
# C. host-side, via the emulator console: no /sdcard round trip (still capped at 3 minutes)
adb -s emulator-5554 emu screenrecord start /tmp/rec.webm
adb -s emulator-5554 emu screenrecord stop
```

VERIFIED - both commands answer `OK` and the output is valid WebM. It is an
**emulator-console** feature, so it exists on an emulator and not on a physical
device, and the container is WebM rather than MP4. The output path resolves
against the EMULATOR process's working directory, not the caller's, so pass an
absolute one. With no on-device file to pull, it is the natural route for a
device e2e runner. **It is capped at 3 minutes too**: on an API 36 AVD a console
recording stopped itself at exactly 180.0 s with no error and no marker, the
`stop` that followed answering as usual (measured 2026-10-05). A flow longer than
that is recorded as consecutive segments, each started before the previous one
would hit the cap; check every segment's duration (`ffprobe`) rather than trusting
that the file ends where the flow did.

Stock limits on the on-device recorder (A and B): **~3 minutes** per recording
by default, which `--time-limit <s>` can shorten but not exceed; **no audio**;
`--bit-rate` and `--size` exist, and non-native sizes can distort.

**A headless recording does not show a Lottie overlay.** Booted with
`-no-window -gpu swiftshader_indirect` and recorded by any of the three routes
above, a `lottie-react-native` layer is BLANK in every frame while the animation
runs to completion underneath (`onFinish` fires and a once-flag gated on it is
written): lottie-android animates, the recording path does not composite that
layer at frame rate. Measured 2026-09-11 on an API 36 AVD, with an asset that a
physical device plays as the control: equally blank on the same build, AVD, tap
and recorder. A blank overlay in such a recording is therefore not a finding, and
the recording cannot confirm a Lottie renders either - iOS or a physical device
answers that (`SKILL.md`, the capture table). Before calling any blank overlay a
fault, record the shipped asset through the same build and route first.

**What is NOT an emulator property: a sub-second `onFinish` on a multi-second
animation.** That is an app bug. `reset()` reaches Android as
`cancelAnimation()`, and a cancel emits `onAnimationFinish` with
`isCancelled = false` - a completion for an animation that has not run a frame -
so a host that rewinds before playing and acts on its first completion cuts
itself off immediately. With the rewind removed from the first play, the same
asset on the same AVD reports its authored duration (measured 2026-09-11). Treat
a short completion as a defect to chase, not as recorder noise.

Whether a recorded device video is an acceptable artifact for a UI review at
all is the install's convention: its UI evidence gate owns it, and the
install's `CONTEXT.md` records the ruling or that there is none.

## 7. Facts worth not re-deriving

| Fact | Consequence |
|---|---|
| Every `adb` call is `-s <serial>` | `adb -e` cannot say *which* emulator and refuses once two are up |
| `sys.boot_completed=1` is the gate | it lags package-manager readiness by ~22s, so it is strictly sufficient; `wait-for-device` is not |
| "Installed" is per-AVD | each AVD has its own data partition; `--no-build` on a fresh AVD correctly dies |
| The Metro host is compiled in | a deep link naming a different host points JS at one machine and the backend at another |
| `--method` has no default | bundling comes from `--method` and nothing else, so every caller - a CI workflow included - passes it |
| The build script starts the emulator `nohup`'d and detached | it must outlive the run that started it, or the app it launched dies with it |
