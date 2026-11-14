---
name: device-emulators
version: 3
description: >
  Running a hot-reloading dev build of a React Native (Expo) app on a simulator
  or emulator - BOTH platforms, iOS Simulator and Android AVD. What a machine
  needs (a developer workstation AND a fresh CI agent), the commands that put a
  Metro-loading dev build on a booted device, how to re-run it without
  rebuilding, how to capture a screenshot or a video, what a virtual device can
  and cannot say about a CAMERA bug, and the traps that make a working build
  read as a broken one. Load before the first simulator or emulator run on a
  machine, before wiring such a step into CI, when a run fails in a way the
  build script does not already explain, and whenever something new is learned
  so it can be written down here. The BUILD/INSTALL/LAUNCH mechanics belong to
  the install's build script (`/tooling-index` indexes it); this skill is the
  operator's route through it plus the machine-level facts that must be true
  first.
requires_install: true
---

# Device emulators

**Scope: a React Native app built with Expo**, whose debug build is a dev client
(`expo-dev-client`) that loads its JS from the Metro bundler, built locally with
the EAS CLI through the repository's own build script and served by its own
dev-stack script. Section *The two scripts* states what this skill expects of
those two scripts. Everything a particular install has - which scripts, which
devices and AVDs, a remote Mac - is a key in the install's `config.json` or a
line of its `CONTEXT.md`, both in the skill's install context
(`fleet where device-emulators`).

One skill, both platforms. A dev build is a **native shell with no JS in it**.
Metro serves the JS; the shell loads it over the network at launch and re-loads
changed modules over a websocket while it runs. So the loop is always two
processes, and the order is fixed: **Metro first, build second** - the build
script refuses `--method <build.method_metro>` with no reachable Metro.

Hot reload is a property of that arrangement, not a flag: once the app is
running, an edit reaches it in seconds with **no rebuild and no reinstall**.
That much is identical on iOS and Android. Everything below the JS layer is not,
which is why there are two platform files in `technical/` and not one.

**This file names no host, path, device, AVD, UDID, bundle id or project.**
Every concrete value is a key in the install's `config.json`, written as
`` `android.avd.default` `` and never as the value; `<key>` inside a command
block means substitute that key's value.

## Layout

| File | Holds | Where |
|---|---|---|
| `SKILL.md` (this) | the model, the two scripts' interface, the route, and the traps common to both platforms | the skill |
| `technical/hot-reload.md` | how to PROVE the refresh, and what it does not cover | the skill |
| `technical/ios.md` | iOS: prerequisites, fresh macOS CI agent, scheme approval, the loops (including the REMOTE one, section 4a: Metro on a non-Mac host, simulator on a Mac over SSH), captures, input | the skill |
| `technical/android.md` | Android: prerequisites, the loops (Metro and sideload), input, captures, the boot gate | the skill |
| `technical/camera.md` | what a virtual device can and cannot say about a camera bug, per platform; permissions and app state headlessly; the N-cold-starts method | the skill |
| `luma.py` + `luma.test.py` | feed-vs-known-black luma of a screenshot, no image library: the instrument that makes "black" a measurement | the skill |
| `config.example.json` | every key `config.json` must carry, and how to obtain it | the skill |
| `config.test.mjs` | the config twins in agreement: the install's `config.json` vs `config.example.json`, every example key named in this skill's prose, and the JDK floor and predicate shared with the build script. Exits `0` / `1` / `3` NO VERDICT - a green from it is only meaningful because it proves its own comparator first | the skill |
| `installation/` | how to make a machine ready, `check` to prove it is, and `check.test.py` driving `check`'s states against the fleet's fixture install (its header lists each case, and the legs that have none) | the skill |
| `config.json` | this install's scripts, artifact names, device and AVD choices, and the remote Mac's coordinates and Metro-host command. An install's build script may read keys from it at run time (section *The two scripts*); the install's `CONTEXT.md` says which | the install context |
| `CONTEXT.md` | which project and machines, what this install's scripts print and leave behind, and what is not ruled | the install context |
| `installation/.install-state.json` | this install's per-host install record | the install context |

**What an adopter supplies.** The build script, the dev script and the
hypervisor probe that `build.script`, `build.dev_script` and
`android.hypervisor_probe` name are the INSTALL's code, not files of this skill.
An adopter points those keys at their own and edits no file of this skill: a
script that implements the interface in *The two scripts* uses the command
blocks as written, and one that takes other arguments gets its own forms of the
affected blocks in the install's `CONTEXT.md`, which outranks this file
(`/claude-skill` section 3, the precedence order). **Everything else is stock platform
tooling and holds unchanged**: the Android SDK resolution order and the
PATH-is-not-the-oracle trap, the `sys.boot_completed` gate, the `-s <serial>`
discipline, `adb input`, the sideload and launch commands, `simctl`'s scheme
approval, capture and launch behaviour, and both input sections. That boundary
is written down because **it is invisible from inside the files**: a command
block parameterised by `<build.script>` looks portable, and it is portable
exactly as far as the script behind the key implements the interface.

**Before the first run on a machine, run `installation/check`**
(`python3 "${CLAUDE_SKILL_DIR}/installation/check"`). It reads the install's
`config.json` and per-host record through the install context. Exit `0` ready;
`1` no install recorded for THIS machine, one against an older `version`, or
NOT FULLY MEASURED (no install context to read, or a leg the probe cannot
measure on this machine: the line says NO VERDICT and names it); `2` not
installed, the line naming the one missing artifact, per platform. Do not
proceed on `1` or `2`; `installation/INSTRUCTION.md` is the procedure for both.

On Android, before it looks at the AVD list, it asks whether an AVD could
**boot**: on Linux the KVM device present, openable by this user, and `emulator
-accel-check` green. Those are different facts from "an AVD exists", and only
the second shows in `emulator -list-avds`, so an AVD list is not evidence a
machine runs anything. The legs live in the probe the install supplies
(`android.hypervisor_probe`), and a probe that cannot measure a platform - macOS,
where the accelerator is HVF and there is no `/dev/kvm` - answers NOT MEASURED.
`check` then exits `1` naming that leg, after every leg it can measure, because
exit `0` means proceed and nothing unmeasured may say that. The cost is stated
rather than hidden: a Mac that runs both platforms reads `1` overall, so it
checks each on its own (`check ios`, `check android`) and confirms the Android
accelerator by hand with `emulator -accel-check`. On the remote iOS route,
before it opens an ssh, it asks whether the Mac's hostname resolves - the one
failure there that no key or host-key fix touches.

`check` takes an optional platform (`ios` | `android`) and otherwise checks
every platform in `platforms.enabled`, exiting on the **worst** state it finds.
**A platform this machine does not run belongs OUT of `platforms.enabled`,
not in it failing.** Otherwise one absent SDK reports the whole skill as
uninstalled and blocks the platform that works.

`check` is also this skill's **only** machine inventory. Its `0` line prints the
versions, runtimes and AVDs this machine actually has, and nothing anywhere
transcribes them: an install is worked from several machines and its config
files are committed, so a written-down inventory is wrong everywhere but where it
was written while still reading as authoritative. Ask the machine.

## The two scripts

The dev script and the build script, plus the two files beside them that the
skill also relies on: the env-config file the build script sources and the
hypervisor probe. Every command block in this skill and in `technical/` is
written in the grammar below. It is the interface the keys point at, and an install whose scripts take
other arguments writes its own forms in its `CONTEXT.md`, which outranks the
blocks here; the rest of each section still applies. The iOS rows - the
simulator target's device choice, `-y`, `--sign` with a simulator target, and
`HOST_IP` for the remote route - are the interface table at the top of
`technical/ios.md`. The install's `CONTEXT.md` also names what its scripts add
beyond this - their timeout knobs, their exact failure messages, the functions
that hold each step.

**The dev script, `<build.dev_script>`:**

- `up <build.dev_client_service> --env <env>` serves Metro for the dev client in
  the FOREGROUND and blocks on the bundler. With `--env <build.default_env>` it
  also boots and seeds the local backend emulators. Its banner names the host it
  resolved, the Metro port and the dev-client deep link, and the banner is the
  authority on all three.
- `down` is the whole teardown: it releases everything the serve holds outside
  its own processes (a pid file, a materialized env file, a machine-wide port
  claim).
- It writes the running stack's ports to `<build.ports_artifact>` (JSON) in the
  checkout it serves, Metro's under `build.metro_port_key`. Parallel stacks on
  one machine each get their own ports, so this file is the only place a port is
  read from.
- It changes into its own directory before doing anything else, so the path it
  is invoked by selects the checkout it serves.
- Its banner also prints the route a person takes to load the dev client on a
  physical phone (trap 9), as the build script's device install does.

**The build script, `<build.script> <ios|android> --env <env> --method <method>`:**

- `--method <build.method_metro>` builds the dev client, which loads its JS from
  Metro; it is refused with no reachable Metro. `--method <build.method_embedded>`
  builds with the JS embedded.
- `--target simulator` builds, installs and launches on a simulator or emulator,
  and is accepted with `<build.method_metro>` only, because a simulator build
  loads its JS from Metro. On Android, `--emulator <avd>` implies it, boots that
  AVD if it is down, and dies BEFORE building on an AVD name `emulator
  -list-avds` does not print; with no `--emulator` it uses the single running
  emulator and dies on zero or several rather than guessing.
- `--no-build` (Android) relaunches the build ALREADY installed on the emulator:
  no build, no install, and it dies when the app is not there.
- `--target file` with `--sign sideload` (Android, embedded) writes
  `<android.apk_artifact>` at the root of the checkout it ran in; `--sign release`
  writes `<android.aab_artifact>`. An iOS simulator build unpacks its `.app` from
  `<ios.sim_artifact>`.
- `--dry-run` prints the routing, including `identity=` and `scheme=`, and builds
  nothing.
- Every simulator or emulator launch is ONE cold launch that names Metro, and it
  then waits for the dev launcher's recently-opened registry to record that load
  (trap 9). It writes the emulator's log to
  `${TMPDIR:-/tmp}/<project.artifact_prefix>-emulator-<avd>.log`.
- Before Gradle it exports `ANDROID_HOME` and a `JAVA_HOME` that is a JDK at or
  above `android.jdk_min_major`, qualified on `bin/javac`. When it reads that
  floor from the install's `config.json` at run time and keeps a fallback for a
  checkout without one, the fallback is the literal
  `ANDROID_JDK_MIN_MAJOR_FALLBACK=<n>`, which `config.test.mjs` pins equal to the
  key.
- `<build.env_config_script>` is the shell file it sources for per-env values:
  `env_config <env> <field>` prints one (`app_identifier` is the embedded build's
  application id). `--dry-run` is the route to an identity everywhere else.

What the build script also does, which the rest of this skill states as fact
and an implementation owes, because each one is a trap it closes:

- It resolves the Android SDK in the order `technical/android.md` section 1
  gives, the same order `installation/check` uses.
- It REFUSES an explicitly exported `JAVA_HOME` that is a JRE or below the floor,
  rather than building against a different JDK.
- It starts the emulator `nohup`'d and detached, so the emulator outlives the
  run that started it; on Linux with `$DISPLAY` and `$WAYLAND_DISPLAY` both empty
  it boots headless (`-no-window -gpu swiftshader_indirect`) and windowed
  otherwise, with a knob that forces either mode on every platform.
- It waits for `sys.boot_completed=1` before installing, on every simulator
  path.
- It reads each APK's application id with `aapt2` and refuses an install whose
  id is not the build's, which is why `installation/check` requires `aapt2`.
- It dies rather than carry on when the build did not rewrite its artifact
  during this run.
- On a failed attach it tells a dead emulator process from a slow boot, and
  runs the hypervisor probe to name the remedy (`technical/android.md`
  section 1).

**The hypervisor probe, `<android.hypervisor_probe>`**, a Python file in the
repository. `check_hypervisor(<emulator path>)` returns `(ok, detail)`, where
`ok` is `True` (usable), `False` (a named cause; `detail` carries the admin
command) or `None` (NOT MEASURED here: a platform the probe does not measure, or
a leg that could not run). **A probe answers `None` where it cannot measure,
never `True` with words saying so**: `installation/check` reads `ok` and not the
prose, so a `True` reads as usable whatever `detail` says. Run as
`python3 <android.hypervisor_probe> probe` it exits `0` usable, `1` a named
cause, `2` not measured. `installation/check` imports it and the build script
runs it when an AVD fails to attach, so both ask the question through ONE
implementation.

**Repository paths.** These keys name files in the install's repository and
resolve against the install root, the directory holding `.claude/fleet.json`
(`/claude-skill` section 2): `build.script`, `build.dev_script`,
`build.env_config_script`, `android.hypervisor_probe`,
`docs.build_machine_components`, `device_e2e.runner` and `device_e2e.flows_dir`,
and the files the scripts write at the root of the checkout they run in -
`build.ports_artifact`, `ios.sim_artifact`, `android.apk_artifact` and
`android.aab_artifact`. Every other path key resolves against `config.json`'s
directory when relative: `device_e2e.driver_path` and `keystore.dir`, both
normally absolute after expansion. `ios.remote.workdir` is a path on the remote
Mac, and its `~` is left for the remote shell.

## The route

Both platforms, same three steps:

1. **Serve** - `<build.dev_script> up <build.dev_client_service> --env <env>`.
   Foreground; background it in a non-interactive session - but **only** for a
   serve nobody else holds a link to. A serve handed to a person is launched
   the way the next paragraph says instead, and backgrounding it is exactly
   what kills it.

   **A serve a person holds a link to is launched as a TRANSIENT SYSTEMD
   USER SERVICE, outside the agent session's own service cgroup.** An
   unattended agent session runs under a systemd service with
   `KillMode=control-group`, which kills by cgroup, so `setsid`, `nohup` and
   `&` do not save the serve from a service restart - they break the process
   tree, not cgroup membership. A transient **service** is forked by the user
   systemd manager, so the serve's parent is that manager and never the
   launching shell: no process group, no session and no walk of the launcher's
   descendants can reach it, and its output goes to the journal by
   construction.

   ```
   XDG_RUNTIME_DIR=/run/user/$(id -u) \
   DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus \
     systemd-run --user --unit=<agent>-serve-<worktree> \
     --setenv=PATH="$PATH" \
     <worktree>/<build.dev_script> up <build.dev_client_service> --env <env>
   ```

   Read it with `journalctl --user -u <agent>-serve-<worktree> -f`; stop it
   with `systemctl --user stop <agent>-serve-<worktree>` **followed by**
   `<worktree>/<build.dev_script> down` (both are needed - see *Stopping*
   below).

   **Every line of that command is load-bearing, and each was measured
   2026-09-12.** Deleting one does not fail the launch; it makes the launch
   lie:

   - **Both env vars** are required from an agent shell; without them
     `systemd-run --user` fails with `Failed to connect to user scope bus`.
   - **`--setenv=PATH="$PATH"`.** The user systemd manager's own PATH is the
     bare system one, with no version-manager node on it. Without this flag the
     serve prints its ENTIRE success banner - ports, Metro port, the
     dev-client deep link - and only then dies **exit 127** (`npx: command not
     found`) as it execs the bundler. Nothing in the serve's own output
     distinguishes it from a healthy one; only the unit's `ExecMainStatus`
     does. The failure is invisible at exactly the place anyone would look for
     it, and the deep link in that banner is the one a tester is about to be
     handed.
   - **The ABSOLUTE `<worktree>/<build.dev_script>` path, never a relative
     one.** `systemd-run` makes a relative command path absolute against the
     CALLING shell's cwd before handing it to systemd. An agent whose cwd is
     the main checkout therefore serves THE MAIN CHECKOUT - claiming its ports
     and writing its runtime files there - under a unit named after the
     worktree it meant to serve. **`--working-directory` does NOT prevent
     this**: it sets the process's cwd, and the command path has already
     resolved by then. The absolute path is also why `--working-directory` is
     absent from the recipe entirely: the dev script changes into its own
     directory before it does anything else (*The two scripts*), so the path
     alone selects the tree.
   - **No `--scope`.** A scope is a cgroup boundary and **not** a signal
     boundary: `systemd-run --user --scope` runs the command as a CHILD of the
     launching shell, so the serve dies with that shell's process tree, and its
     stdout/stderr go to the caller's terminal - where a serve that dies leaves
     no diagnosable line anywhere, because the journal holds only the scope's
     one `Started` line. Wrapping it in `setsid nohup ... > serve.log 2>&1`
     does rescue both halves (measured surviving `kill -TERM -- -<pgid>` plus a
     SIGHUP of its launcher, Metro still answering 200), but the serve remains
     a direct child of the launching shell for as long as that shell lives, so
     anything that walks the launcher's descendants still reaches it, and the
     only copy of the log is one redirect away from being lost. A service has
     neither property to rescue, which is the whole reason it is the smaller
     recipe.
   - **Only `<build.dev_client_service>`, never a web variant.** The unit
     lives as long as its main process; `up <build.dev_client_service>` blocks
     on the bundler, while a service that backgrounds its processes and exits 0
     is reaped by systemd, its whole cgroup with it, seconds after a clean
     banner. A web serve belongs to the browser e2e harness (`/e2e-suite`) and
     the install's capture scripts, runs from a normal shell in the worktree,
     and is never a unit and never handed to a person.

   **Confirm the cgroup escape by MEMBERSHIP, never by the process tree**:
   `grep <metro pid> /sys/fs/cgroup/system.slice/<the session's unit>/cgroup.procs`
   must find nothing, and `cat /proc/<metro pid>/cgroup` must end in
   `<agent>-serve-<worktree>.service`.

   **Stopping: the suffix is part of the name, and stopping the unit is
   not a teardown.**

   - `systemctl --user stop <name>` resolves a bare name to `<name>.service`,
     which is right for this recipe and **wrong for any scope**: against a
     scope the bare name reports `Unit <name>.service not loaded` (rc 5) while
     the serve goes on answering 200 - a refusal that reads exactly like
     "already stopped". A scope is stopped as `<name>.scope`.
   - Stopping the unit kills the serve's cgroup and does nothing else. A cgroup
     stop signals the dev script and the bundler at the same instant, so an
     exit trap that cleans up only once the bundler is already gone never does,
     and whatever the serve holds outside its processes - a pid file, a
     materialized env file, `<build.ports_artifact>`, a machine-wide port claim -
     survives the stop. **Only `<worktree>/<build.dev_script> down` releases
     it**, so run it after the stop. Run alone it performs the whole teardown,
     but the unit then ends `failed` (exit-code) and lingers under that name
     until `systemctl --user reset-failed <name>`. What this install's dev
     script leaves behind, and the line its `down` prints, are in `CONTEXT.md`.

   User units stop with the user's last login session unless `loginctl
   enable-linger` is set, which is machine state and the operator's call.

2. **Build, install, launch** - one command per platform. iOS uses
   `--target simulator`; Android uses `--emulator <avd>`, which implies it.
   Both build locally, install, launch, and point the dev client at Metro.
   The exact invocations are in the two platform files.
3. **Iterate** - edit JS, and nothing else. Native config, a new native module,
   or an `EXPO_PUBLIC_*` key change means step 2 again.

**Steps 1 and 2 need not be the same machine, and on iOS they often cannot
be**: a simulator exists only on macOS, so an operator on any other OS serves
Metro locally and drives the build and the simulator on a Mac over SSH. Step 3
is unchanged there - Metro reads the operator's own working tree, so Fast
Refresh crosses the link with no rebuild and no re-sync. The route, its setup
and its traps: `technical/ios.md` section 4a.

**The two platforms are not symmetric at step 2, and the asymmetry is the
build script's, not this skill's.** Android has `--no-build`, which relaunches
the build ALREADY installed on the emulator in seconds, installing nothing and
running no Gradle; iOS has no such flag because the build script's iOS
simulator path already builds, installs and launches in one pass, and its
equivalent shortcut is `simctl launch` (`technical/ios.md`), which restores the
app but re-points nothing (trap 9). Do not look for `--no-build` on iOS: the
build script rejects it by name.

## Driving and capturing a running device

What each platform can do headlessly, with the file that has the commands:

| | iOS Simulator | Android AVD |
|---|---|---|
| screenshot | yes: `simctl io ... screenshot` | yes: `adb exec-out screencap` |
| video | yes: `simctl io ... recordVideo`, stopped with `SIGINT` | yes: three routes; `screenrecord --time-limit` is the safe one |
| tap / swipe / type | via a DRIVER only (`device_e2e.driver`, for example Maestro) - `simctl` cannot | yes: `adb shell input`, first-party |
| needs no visible window | yes | yes |
| camera | none; the preview still mounts but paints nothing, so the feed shows the app's own ground under it and its colour says nothing about the mount | a virtual scene; captures are a synthetic black JPEG by design |
| a Lottie overlay (`lottie-react-native`) | yes: lottie-ios paints it; a recorded frame matches the web render of the same frame | NO: headless (`-no-window -gpu swiftshader_indirect`) + `adb screenrecord`: the layer is BLANK in every frame while the animation itself runs to completion |

All of it verified 2026-09-03. The commands, the exit-code caveats and the races
are in `technical/ios.md` sections 6-7 and `technical/android.md` sections 4-6;
the camera row, and what a virtual device can adjudicate about a camera report,
is `technical/camera.md`.

**The Lottie row makes a headless AVD recording a dead instrument for Lottie
artwork, in BOTH directions.** lottie-android runs the animation and `onFinish`
fires, but the recording path does not composite that layer at frame rate, so
every frame shows the screen beneath. Measured 2026-09-11 on an API 36 AVD: an
asset that a physical device plays and a freshly exported one were equally
blank, on the same build, the same AVD, the same tap and the same recorder. So
**a blank Lottie overlay in an Android emulator recording is NOT a finding, and
the Android arm cannot confirm that a Lottie renders either**; iOS or a
physical device is the instrument for Lottie artwork. **The control idiom**:
before calling a blank overlay a fault, run the SHIPPED asset through the same
build and the same capture route - a blank overlay is a finding only when that
control renders. `technical/android.md` section 6 carries the same fact at the
recorder.

**A sub-second `onFinish` on a multi-second animation is an APP BUG, not an
emulator one, and reading it as emulator behaviour costs a real defect.**
`reset()` reaches Android as `cancelAnimation()`, and a cancel emits
`onAnimationFinish` with **`isCancelled = false`** - a completion event for an
animation that has not run a frame - so any host that rewinds before playing
and then acts on its first completion cuts itself off almost immediately. With
the rewind removed from the first play, the same asset on the same AVD reports
its authored duration (measured 2026-09-11, API 36 AVD). So a completion far
shorter than the authored length is a signal to chase, and the only thing this
rig genuinely cannot tell you is what the frames LOOKED like.

An install's device e2e suite, where it has one (`device_e2e.runner`, with its
flows under `device_e2e.flows_dir`), is built on exactly this table, on both
platforms: the same flow files drive the Simulator and an AVD through
`device_e2e.driver`.

## The traps common to both platforms

Each one has already presented as something other than what it was.

1. **A no-op `touch` is not a test of hot reload.** Metro keys on content, so
   `touch` on an unchanged file produces nothing - indistinguishable from a
   broken watcher. `technical/hot-reload.md` has the probe that does work.

2. **The Metro port is not the default one.** It comes from the running stack's
   port artifact (`build.ports_artifact`, key `build.metro_port_key`), because
   parallel worktrees each hold their own ports. Reading a port from
   documentation instead of from that file points a build at a neighbour's stack.
   **This holds for EVERY `--env`, cloud backends included**, and that is the
   half a reader talks themselves out of: a cloud-backend stack starts no
   emulators, so "it needs no ports" is an easy inference and it is wrong - Metro
   is not an emulator, and the serve claims ports like any other. So the deep
   link a cloud-env dev-client serve prints carries its own port, not the default
   one, and a build pointed at the default reaches whichever worktree holds it.

3. **The identity and scheme are per (env x method), so derive them.** Add
   `--dry-run` to the step-2 command and it prints `identity=` and `scheme=`.
   A hardcoded bundle id, application id or scheme belongs to exactly one build
   and is silently wrong for every other - and on both platforms a wrong scheme
   fails without looking like an error (`technical/ios.md` section 3, where a
   scheme with no approval for the bundle id raises a dialog and `openurl`
   exits 0 having launched nothing; Android's scheme-mismatch note in
   `technical/android.md` section 3a).

4. **The Metro host is compiled into the build.** One substitution repoints
   Metro AND every backend emulator together, so a wrong host does not degrade -
   it disconnects everything at once. Never hand-substitute a loopback or an
   emulator-alias address; the dev script and the build script must resolve it
   with the same function precisely so they agree.

5. **An exit code is not an oracle on either platform.** `simctl openurl` exits
   0 with nothing launched; `simctl launch` prints a pid for an app that then
   loads nothing; `am start` exits 0 printing *"Activity not started"*;
   `adb shell input tap` exits 0 into empty space. Assert on the CONSEQUENCE -
   the focused window, a screenshot that differs, a pid, a line in Metro's
   output - never on the status. Both platform files name the positive evidence.

6. **The local build is not offline.** The build CLI declares a logged-in
   context even with its local-build flag, so an unauthenticated agent fails at
   the build, not at a login step. On CI, supply the token in the variable
   `ci.eas_token_env` names.

7. **"Installed" is per device.** Each simulator and each AVD has its own
   storage, so a build present on one is absent from the next, and a
   re-run-without-building on a fresh device correctly dies rather than
   reporting success over an older build.

8. **Driving the screen is NOT symmetric, and the asymmetry decides how an
   automated job is designed.** Android taps headlessly with no extra tool
   (`adb shell input`, coordinates in device pixels). iOS has **no tap in the
   installed toolchain**: `simctl ui` sets UI *options*, not input, and the two
   routes that do exist (`idb`, an XCUITest target) are both outside it.
   `osascript` is not a route - it needs macOS Accessibility permission and
   prompts interactively. A test suite closes the gap with a driver
   (`device_e2e.driver`), but **an OPERATOR step that needs a tap is still
   REMOVED, not automated**: it is why the URL scheme is pre-approved rather
   than the dialog clicked, and why the dev client's first-run sheet is
   addressed by a preference rather than by pressing Continue. Reaching for the
   test driver to dismiss a dialog makes every run depend on a JVM and a driver
   install to get past something that should not be there. Read
   `technical/ios.md` section 7 before designing anything that expects a finger.

9. **A PLAIN LAUNCH LOADS THE LAST-OPENED BUNDLE, WHICH ON A SHARED BOX IS
   OFTEN SOMEBODY ELSE'S SERVE.** The installed dev client runs the Expo dev
   launcher with launch-last-bundle on, so a plain launch - tapping the icon,
   `simctl launch`, an `am start` of the main activity WITH the launcher intent
   (`-a android.intent.action.MAIN -c android.intent.category.LAUNCHER`) - skips
   the launcher screen and loads the most recent entry of the launcher's
   recently-opened registry. (A bare `am start -n <activity>` carries no action
   and loads NOTHING: it stops on the launcher screen - measured 5 of 5,
   `technical/android.md`.) On a box running several Metro serves on different
   ports that entry is whichever serve was opened last ON THAT DEVICE, routinely
   another worktree's or the tester's. **Nothing looks wrong**: every serve
   answers `GET /status`, the app renders, navigates and talks to a backend, and
   the screenshot or e2e verdict taken from it measures somebody else's tree -
   which reads exactly like a real regression in yours.

   **A SCREEN deep link does not re-point the bundle.** It opens that route
   in whatever bundle is already loaded. Only a launch that NAMES the serve
   selects one, and it must be a COLD launch that loads the app ONCE:

   - **iOS**: `simctl launch --terminate-running-process <udid> <bundle id>
     --initialUrl http://<host>:<port>`. **Never a cold `simctl openurl` of the
     dev-client URL**: on a build that bakes a live default launcher URL it loads
     the app TWICE, and that crashes cold starts (`technical/ios.md` section 4,
     measured).
   - **Android**: `am force-stop`, then ONE `am start -a
     android.intent.action.VIEW -d "<scheme>://expo-development-client/?url=http%3A%2F%2F<host>%3A<port>"
     -n <activity>`. **Never a plain `am start -n` first**: it parks the app
     on the launcher screen and the deep link after it loads nothing
     (`technical/android.md`, measured 5 of 5).
   - **A physical phone** gets neither: the build script launches nothing
     there, so a PERSON loads it, by the route the dev-client serve banner and
     the build script's device install print: open from the icon, then the dev
     menu's Go home -> Enter URL manually. **Never by opening the dev-client URL
     from outside the app on iOS** - a cold open is the same double load as the
     cold `openurl` above.

   The build script's simulator and emulator launch already does exactly this,
   and proves the load (*The two scripts*). An install's device e2e runner may
   do it too: the install's `CONTEXT.md` says on which platforms, and on a
   platform where the runner does not, point the emulator first with the build
   script's `--no-build` launch. By hand, the port comes from the running
   stack's port artifact (trap 2), never from a document. Do it **before
   every capture and every test run**, not once per session: it makes your serve
   the most recent entry only until anyone else opens theirs.

   **Then verify it took**, because a launch is a request (trap 5: the exit
   status is not an oracle) and the launcher still falls back to the launcher
   screen when the serve is slow to answer. Two instruments, each with its read
   command in the platform file: the launcher's own **recently-opened
   registry**, whose newest `timestamp` is what a plain launch will load and
   whose `url` names the port it took; or a **bundle marker only the intended
   serve carries**, observed in the running client and measured ABSENT from
   every other serve on the box.

10. **A keyboard bug needs a SOFTWARE keyboard, and on the iOS simulator
   "Connect Hardware Keyboard" removes it.** No on-screen keyboard means no
   keyboard height reaches the app, so a sheet that lifts off the screen, a
   field left under the keyboard, or an offset frozen mid-hide cannot happen -
   and the flow meant to reproduce it passes. Prove the keyboard is on screen
   (a screenshot, or `inputView` in the hierarchy) before believing any
   keyboard run, on either platform: `technical/ios.md` section 7. A HID
   key event from a tap driver (AXe's `type`/`key`) switches the simulator to
   that same hardware-keyboard mode, and an accessibility-tree read still lists
   the keys there, so on iOS only the screenshot is proof (section 7).

## Config keys

Every key `config.example.json` carries, and where it is used. The example's
`_comment` keys say how to obtain each value.

| Key | What it is |
|---|---|
| `project.name`, `project.artifact_prefix` | what the loops run for (prose only), and the leading component of the build script's emulator log and of the screenshot path `technical/android.md` section 5 writes |
| `platforms.enabled` | the platforms THIS install runs; `check` checks each |
| `build.script`, `build.dev_script`, `build.env_config_script` | the two scripts and the per-env value file (*The two scripts*) |
| `build.dev_client_service`, `build.default_env`, `build.method_metro`, `build.method_embedded` | the words the route substitutes into those scripts' grammar |
| `build.ports_artifact`, `build.metro_port_key` | where the running stack's Metro port is read from (trap 2) |
| `ios.sim_artifact`, `ios.device_type`, `ios.device_type_id`, `ios.xcode_min_major` | the simulator build's archive, the device the team standardises on in both its forms, and the Xcode floor `check` enforces |
| `ios.dev_menu_onboarding_key` | the preference that suppresses the dev client's first-run developer-menu sheet (`technical/ios.md` section 8) |
| `ios.sweep_extra_device_types`, `android.sweep_short_screen.size`, `android.sweep_short_screen.density` | the further devices an install's visual sweep runs on, where it runs one: extra simulators, and a display override that makes `android.avd.default` a short phone (`technical/android.md` section 4) |
| `ios.remote.host`, `ios.remote.user`, `ios.remote.workdir`, `metro.host_cmd` | the remote iOS route: the Mac, the account, the operator's directory there, and how the serving host is asked for its address (`technical/ios.md` section 4a) |
| `android.hypervisor_probe` | the repository's hypervisor probe (*The two scripts*) |
| `android.apk_artifact`, `android.aab_artifact` | the embedded build's outputs (`technical/android.md` section 3b) |
| `android.avd.default`, `android.avd.compat` | the AVD the team standardises on, and the optional second one a change is checked against |
| `android.jdk_min_major` | the JDK floor `check` enforces and the build script exports against |
| `keystore.dir` | the directory holding the Android signing keys, outside every checkout (`technical/android.md` section 3b) |
| `ci.eas_token_env` | the NAME of the variable carrying the build CLI's token (trap 6) |
| `docs.build_machine_components` | the repository document pinning the SDK components, build tools and JDK a build machine needs |
| `device_e2e.driver`, `device_e2e.driver_path`, `device_e2e.runner`, `device_e2e.flows_dir` | the optional device e2e suite: its tap driver, where the driver's installer puts it, the runner and its flows |

## Where the rest lives

- **`/tooling-index`** - the install's tooling index: the build-script and
  dev-script rows, every flag and its refusals, and both device loops, one line
  each. Read it before assuming a helper is missing.
- **`/repo-and-environments`** - what `--env` selects, why the Metro host is
  compiled into the build, and the native-feeding env sources (section 6.5).
- **The build script itself** - the authoritative account of artifact
  extraction, device selection, the boot gate and the one-load launch and its
  proof, each with the measurement that justifies it. The install's `CONTEXT.md`
  names the functions that hold each step.
