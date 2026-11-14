# iOS Simulator: prerequisites and loops

Universal. Values come from this skill's `config.json` in the install context
(`fleet where device-emulators config.json`); `<key>` below means substitute
that key's value. Measured facts carry the date and the platform they were
measured on, because the date is a re-check trigger.

**The command blocks here are written in the grammar of SKILL.md *The two
scripts***, the interface the install's build and dev scripts implement; where
its scripts take other arguments, the install's `CONTEXT.md` carries its own
forms and outranks the blocks here. **Everything else in this file is stock
platform tooling** (Xcode, `simctl`, `plutil`, `ssh`, `rsync`) and holds on any
machine. The iOS rows of that interface, which sections 1, 4 and 4a rely on:

| The iOS rows | What the sections below rely on |
|---|---|
| device choice, `<build.script> ios ... --target simulator` | it takes no device id: it installs onto the first simulator the TEXT form of `xcrun simctl list devices` prints as booted, with `xcrun` found through PATH (the section 4 shim relies on both); with none booted it boots the first available iPhone, and with none available it dies `no available iPhone simulator to boot`. It names the device it chose in one line, `[ios-sim] Using already-booted simulator <UDID>` |
| the `.app` it installs | unpacked from `<ios.sim_artifact>` at the root of the checkout it ran in; it dies if the build did not rewrite that tarball during this run, or if the `.app`'s `CFBundleIdentifier` is not the identity it built for |
| its closing banner | names the simulator UDID it installed to and the Metro URL it pointed the app at |
| `-y` | skips the build's confirmation prompt |
| `--sign <mode>` with `--target simulator` | `release` is refused as contradictory; any other mode is accepted, warned about and dropped, and the build continues unsigned |
| `HOST_IP=<serving host>` in the build's environment | names the machine serving Metro when it is not the one building (section 4a) |

Every place below that hands a value to "the install's `CONTEXT.md`" is a line
an adopter fills in there.

## 1. Prerequisites (any machine)

| Needs | Prove it | Why |
|---|---|---|
| Xcode + a selected developer dir, at least `<ios.xcode_min_major>` | `xcode-select -p`; `xcodebuild -version` | `simctl` and the build both resolve through it; the key is a FLOOR, not a pin |
| Its licence accepted | `xcodebuild -version` exits 0 | an unaccepted licence fails every build with a licence error, not a build error |
| >= 1 iOS **runtime** | `xcrun simctl runtime list` | a device with no runtime is not "available" and cannot boot |
| >= 1 available iPhone **device** | `xcrun simctl list devices available` | the build script picks the FIRST booted one (section 4), else the first available iPhone; with none it dies |
| CocoaPods | `pod --version` | the prebuild step runs `pod install`; absent, the build dies `spawn pod ENOENT` |
| Node + the repo's dependencies | `node -v`; the repo's dependency install (`/worktree-workflow` section 1.3) | Metro and the build CLI |
| Build CLI authenticated | `ci.eas_token_env` set, or a stored session | the local build declares a logged-in context (SKILL.md trap 6) |
| python3 | `python3 -V` | the scheme-approval write (section 3) and a scripted read of the dev launcher's registry (section 4) parse binary plists with `plistlib`. `installation/check` is itself python3, so it proves this only when run ON the Mac, never on the remote route |

`installation/check` asserts that table in one command and one line, with two
gaps worth knowing: it never runs the dependency install, so a **fresh worktree
with no `node_modules` passes it**, and it does not assert section 1.1 at all,
which is that section's whole subject.

**A simulator does not need `Simulator.app`.** `simctl boot` works with no
window; a build script that runs `open -a Simulator` treats it as a convenience
and tolerates its failure. This is what makes the whole loop viable on a
headless agent.

**`xcode-select -p` has a WRONG answer that is not an error**: a path ending
in `CommandLineTools`. The command line tools alone satisfy `xcrun` and carry
no simulators at all, so the mistake surfaces two rows later as "no available
iPhone simulator" - a missing-device problem that no amount of creating devices
fixes. Install the full Xcode and select that
(`installation/INSTRUCTION.md`, iOS step 1).

### 1.1 Three prerequisites `check` cannot cover, and the trap under them

**`check ios` interrogates the machine that BUILDS.** Two of the three below
belong to the machine that SERVES the stack - a different machine entirely on
the remote route (section 4a) - and the third is a subprocess the build CLI
spawns well into the Xcode leg, long after the point where anyone is still
watching. No single probe spans that, so these are proved by hand once, exactly
like 4a.1 step 5. None of them is a matter of taste: the absence of each one
blocks a step.

**So a machine `check` calls installed can still be missing all three**, and
that is not a defect in `check` - it is the reason this section is prose rather
than a probe, and the reason none of it is a version-bearing install step in
`installation/INSTRUCTION.md`. Read a green `check` as *"the simulator side of
this machine is ready"*, never as *"a build will get through"*.

| Needs | On the machine that | What its absence looks like |
|---|---|---|
| **fastlane** | builds | `spawn fastlane ENOENT` - the build CLI's local iOS build drives fastlane for the Xcode leg |
| **A JVM**, where the local backend emulators are JVM processes | serves the stack | `Unable to locate a Java Runtime` |
| **The backend CLI, installed GLOBALLY**, where it shares its package name with a client SDK | serves the stack | `npx <cli>: could not determine executable to run` |

The install's `CONTEXT.md` names them: the package for each, and where its dev
script resolves the backend CLI and the JVM.

**The global install is not a preference, and the cause is a name collision.**
When the app depends on a package with the SAME NAME as the backend's CLI - its
client SDK - and that package ships no binary, `npx <cli>` resolves the SDK and
dies. A dev script that resolves the CLI prefers a real CLI on PATH and falls
back to `npx --yes <the CLI's own package>`; the comment at that resolver is the
authority on the rule, and this row exists to name the SYMPTOM, which is the
half the rule's own home does not tell you how to recognise.

**`command -v java` LIES on macOS, and this is the trap worth the paragraph.**
macOS ships a `/usr/bin/java` **stub** that always exists and exits non-zero
when no JDK is registered, while a Homebrew JDK is **keg-only** - installed, and
deliberately not linked onto PATH. So an existence check passes on a machine
with no usable runtime AND fails to see the runtime that is actually there. The
test is that `java -version` **RUNS**, never that a `java` binary exists. A dev
script that tests it that way and prepends the keg's bin when it does not spares
the operator a symlink and a profile edit; same class as this skill's refusal
to resolve the Android SDK from PATH (`technical/android.md` section 1).

## 2. A fresh macOS CI agent: the extra steps

An image with Xcode installed still fails on three things a workstation had
done years ago by hand.

```bash
sudo xcodebuild -license accept          # unattended licence acceptance
sudo xcodebuild -runFirstLaunch          # install bundled tools/packages
xcodebuild -downloadPlatform iOS         # the runtime; images ship without one
```

Then make sure a device exists, rather than assuming one:

```bash
xcrun simctl list devices available | grep -q iPhone || \
  xcrun simctl create "<ios.device_type>" "<ios.device_type_id>"
```

`simctl create` takes the device-type **identifier**, not the display name that
`simctl list devices` shows. `xcrun simctl list devicetypes` maps one to the
other.

Also on CI, and only on CI:

- **Export `ci.eas_token_env`.** Nothing else authenticates a non-interactive agent.
- **Pre-approve the URL scheme** (section 3). Mandatory: no operator, no tap.
- **Suppress the first-run sheet** (section 8) - it MAY or may not appear, and
  section 8's leg 1 is the only thing that says which. Optional unless the job
  takes screenshots.
- **Never rely on `osascript`.** It needs Accessibility permission, prompts
  interactively, and without the permission is refused with `execution error:
  ... is not allowed to send keystrokes. (1002)` - measured 2026-09-03. A CI
  agent has nobody to grant it.

## 3. Pre-approving the dev-client URL scheme

Without this, opening a URL in the app's scheme raises a confirmation dialog and
`openurl` exits 0 having launched nothing (SKILL.md trap 5). It binds every URL
open: a hand `openurl`, and a flow's `openLink` of a screen deep link. It does
**not** bind the pointing launch in section 4, which passes the Metro URL as a
launch argument and opens no URL at all - that is one of the reasons it is the
launch. The approval lives per simulator, in a plist keyed by scheme:

```
~/Library/Developer/CoreSimulator/Devices/<UDID>/data/Library/Preferences/com.apple.launchservices.schemeapproval.plist
key:   com.apple.CoreSimulator.CoreSimulatorBridge-->{scheme}
value: {bundle id}
```

Get `{scheme}` and `{bundle id}` from the build script's `--dry-run` output
(`scheme=`, `identity=`) - never hardcode them (SKILL.md trap 3). Write it as a
**binary** plist, merging into what is there:

```bash
xcrun simctl shutdown "$UDID"
python3 - "$UDID" "$SCHEME" "$BUNDLE_ID" <<'PY'
import os, plistlib, sys
udid, scheme, bundle = sys.argv[1:4]
p = os.path.expanduser("~/Library/Developer/CoreSimulator/Devices/%s/"
                       "data/Library/Preferences/"
                       "com.apple.launchservices.schemeapproval.plist" % udid)
data = plistlib.load(open(p, "rb")) if os.path.exists(p) else {}
data["com.apple.CoreSimulator.CoreSimulatorBridge-->" + scheme] = bundle
plistlib.dump(data, open(p, "wb"), fmt=plistlib.FMT_BINARY)
PY
xcrun simctl boot "$UDID" && xcrun simctl bootstatus "$UDID"
```

**The shutdown/boot around the write is load-bearing, and this is the whole
finding.** Measured 2026-09-03 on iOS 26.5 / Xcode 26.6: written while the
device was **booted**, the file was correct on disk and the dialog still
appeared on two subsequent `openurl` calls. The same file, written while the
device was **shut down**, took effect on the next boot and the app launched with
no dialog. The preference daemon inside the simulator reads this at boot.

The plist keeps one entry per scheme, so a machine that has approved several
builds accumulates them and each stays approved.

## 3b. The JS runtime is Hermes, and its `Intl` is NOT the browser's

Measured 2026-09-13 on an iOS 26.5 simulator, printed from a running dev
build's Hermes rather than inferred from a compatibility table:

```
Object.getOwnPropertyNames(Intl.NumberFormat.prototype)
  = ["constructor", "format", "resolvedOptions"]
```

**There is no `formatToParts`, no `formatRange`, and no `Intl.PluralRules`.**
Present and working: `format`, `resolvedOptions`, the static
`supportedLocalesOf`, `Intl.DateTimeFormat`, `Intl.Collator`,
`Number.prototype.toLocaleString`. ICU itself is FULL - `de-DE` resolves to
`de-DE`, `en-IN` groups 2-2-3, and `currencyDisplay:'code'` is honoured - so the
gap is the PARTS ACCESSOR and not the data.

**`format` is an ACCESSOR, so a capability probe written against the prototype
asks a different question than the call site does**: reading
`Intl.NumberFormat.prototype.format` throws `TypeError: ... getter called with
incompatible 'this'`. Probe the INSTANCE.

**Why this is here rather than in a code comment: Android Hermes, node and
every browser have `formatToParts`, so a gate suite cannot tell you this and a
green one is not evidence either way.** The one instrument that can observe it
is a run on the device - which is what this file is for - and the one
instrument that can keep observing it in CI is a shim of the measurement in the
gate suite, not a device run (`/e2e-suite` says what each harness can and
cannot see; the install's `CONTEXT.md` for that skill names where its shim
lives).

**Apple's ICU is not node's, and a gate that shims node proves nothing about
the DATA.** Measured 2026-09-13 by rendering a grid of currencies x locale tags
x values on the simulator and comparing each cell against node: most cells
render the raw string identically, and two classes differ.

- **Apple IGNORES the `-u-nu-` Unicode extension**: `en-US-u-nu-hanidec`
  renders latn digits on iOS and Han digits in node.
- **ICU's own data differs**: `id-ID` spells IDR/INR with no gap
  (`Rp1.234.568`) where node has one, and `ja-JP` uses the yen sign U+00A5
  where node uses the fullwidth yen sign U+FFE5.

The last class is the useful one to remember: **a raw-string difference is not
automatically an app-visible difference** - an app's own formatting layer can
absorb both of those before anything is drawn. Decide what a difference costs
by looking at what the screen renders, not at the formatter's output.

**`DateTimeFormat` IGNORES the `calendar` OPTION.** Measured 2026-09-28, same
simulator: `th-TH` formats 2026 as the Buddhist 2569, and adding
`{ calendar: 'gregory' }` changes nothing but `resolvedOptions().calendar`, which
then claims `gregory` over a 2569. The locale extension `th-TH-u-ca-gregory`
renders 2026. Android Hermes renders 2026 for all three - and, like iOS, has no
`Intl.PluralRules` and no `Intl.RelativeTimeFormat` at all. A static check that
bans the ignored option in app source is the cheap fence; the install's
`CONTEXT.md` names one where it has it.

**Re-measure rather than extending this list on faith.** It is a property of
one Hermes build under one iOS, and the date above is the re-check trigger. A
member added to this list without a measurement behind it makes the shim harsher
than the runtime, which invents failures on a platform nobody ships on.

## 4. The loops

**Ports and host first.** Both come from the running stack, never from a
document: the host from the dev script's banner, the Metro port from
`build.ports_artifact` under key `build.metro_port_key` (SKILL.md trap 2 for the
port, trap 4 for the host).

```bash
# 1. serve (foreground; background it in a non-interactive session)
<build.dev_script> up <build.dev_client_service> --env <env>

# 2. build + install + launch
<build.script> ios --env <env> --method <build.method_metro> --target simulator
```

Add `-y` to skip the build's confirmation prompt. Add `--dry-run` to print the
routing (and the identity and scheme) without building anything.

`--target simulator` forces an **unsigned** build - a simulator runs unsigned
code - so a signing flag is moot there, and the two ways the interface says so
are not the same: `--sign release` is refused, any other `--sign` is dropped
with a warning. So a signed build is one of the things you cannot get by asking
twice: read the warning line, because the run that follows it is not the run
you typed.

You never handle `<ios.sim_artifact>` (the table at the top); a worktree's build
lands it in that worktree, and it is named here because a failed extraction is
diagnosed from it.

**To choose WHICH simulator**, boot it before step 2 - and on a machine where
nobody else has one booted, that is all it takes: the build script uses an
already-booted one and only falls back to "the first available iPhone" when
nothing is booted.

```bash
xcrun simctl boot "$UDID" && xcrun simctl bootstatus "$UDID"
```

**The build script takes no device id: it installs onto the FIRST booted
simulator `xcrun simctl list devices` prints**, so where another session under
the same macOS account has one booted, booting yours does not select it.
(Device sets are per macOS user, so sessions under separate accounts never
collide.) **Symptom**: a green build, install and launch - onto a device you
never booted, terminating and replacing the app someone else was running there,
while yours sits empty. The build names the device it chose in one line:
`[ios-sim] Using already-booted simulator <UDID>`. **Constraint**: make your
simulator the only booted one `xcrun simctl` shows for that one call, with a
PATH shim that passes every `xcrun` call through unchanged except the text form
of `simctl list`, where it reports every other booted device as `(Shutdown)`:

```bash
# The shim. Anywhere of your own on the building machine, first on PATH for
# the build call only.
mkdir -p "$SHIM_DIR" && cat > "$SHIM_DIR/xcrun" <<'SHIM'
#!/bin/bash
# `xcrun simctl list` in text form shows ONLY $SIM_ONLY_UDID as Booted; every other call passes through.
if [ "$1 $2" != "simctl list" ] || printf '%s\n' "$@" | grep -qxE -- '-j|--json'; then
  exec /usr/bin/xcrun "$@"
fi
[ -n "$SIM_ONLY_UDID" ] || { echo "xcrun shim: SIM_ONLY_UDID is unset" >&2; exit 2; }
out="$(/usr/bin/xcrun "$@")" || exit
printf '%s\n' "$out" | grep -F "$SIM_ONLY_UDID" | grep -qF '(Booted)' \
  || { echo "xcrun shim: $SIM_ONLY_UDID is not booted - boot it first" >&2; exit 1; }
printf '%s\n' "$out" | sed "/$SIM_ONLY_UDID/!s/(Booted)/(Shutdown)/"
SHIM
chmod +x "$SHIM_DIR/xcrun"

# The build, with your booted simulator the only one it can see:
xcrun simctl boot "$UDID"; xcrun simctl bootstatus "$UDID"
PATH="$SHIM_DIR:$PATH" SIM_ONLY_UDID="$UDID" \
  <build.script> ios --env <env> --method <build.method_metro> --target simulator
```

Read the `Using already-booted simulator` line back and check it names `$UDID`:
that line, not the build's exit, is the proof the shim took. **The refusal in
the shim is load-bearing**: with `$UDID` not booted it hides every device, the
build script's boot fallback reads the same shimmed listing, finds nothing and
dies `no available iPhone simulator to boot` - instead of booting "the first
available iPhone", which may be the neighbour's. Without it, a typo'd or
shut-down UDID quietly degrades to the very install this shim exists to
prevent. JSON listings (`-j`, `--json`) pass through untouched, so a tool that
parses them is unaffected. Remove the shim directory by its literal path when
the build is done. Measured 2026-09-26 on macOS with another session's simulator
booted under the same account, in a login shell with the shim first on PATH: a
first-booted selection over `xcrun simctl list devices` returned the named
booted device, and with a shut-down UDID it returned nothing where without the
shim it returned the other session's; the rewrite of a second booted device
to `(Shutdown)` was checked against a listing with two booted. A device e2e
runner (`device_e2e.runner`) that defaults to the first booted simulator has the
same exposure unless it is handed a device; the install's `CONTEXT.md` names how
its runner takes one.

**Re-running without a build.** There is no `--no-build` on iOS. There is
something better, because a JS change needs no new binary at all:

| Change | Do |
|---|---|
| JS / TS only | **nothing.** Fast Refresh already delivered it |
| app restarted, or you killed it | point it at your Metro and verify it took (below). A bare `xcrun simctl launch "$UDID" "$BUNDLE_ID"` loads the LAST-OPENED bundle, which on a box running several serves is often another worktree's (SKILL.md trap 9) |
| pointing it at a different Metro | the same launch, with the other Metro's URL |
| native config, a config plugin, a native module, an `EXPO_PUBLIC_*` key | step 2 again |

The first build on a machine is cold - prebuild, `pod install` and the whole
Xcode build - and is measured in minutes; the install's `CONTEXT.md` records
what it measured. The relaunch paths above are seconds.

**Pointing the client at YOUR Metro, and proving it took.** The port comes from
the running stack's port artifact (SKILL.md trap 2), never from a document:

```bash
xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE_ID" \
  --initialUrl "http://<host>:<port>"
```

The build script's own launch IS this pointing launch plus the registry proof
below (SKILL.md *The two scripts*). A device e2e runner that points the app calls
the same implementation, so the launch and its proof exist once; the install's
`CONTEXT.md` names it.

**NOT `simctl openurl` of the dev-client URL on a cold app: it loads the app
TWICE, and the second load kills it.** A build that bakes a default launcher URL
(the dev-client plugin's `defaultLaunchURL`) loads that URL from the launcher's
start-up path when it is cold-launched BY URL, and then loads the same URL again
when the URL is delivered ~200 ms later. When the baked URL is a live Metro - the
normal case, because the build and the serve come from one worktree - two React
hosts initialise at once and the app dies at its first mount with the `SIGTRAP`
in section 8. Measured 2026-09-23, same simulator, same build, 10 cold launches
each, counting the launcher's manifest fetches at a logging proxy in front of
Metro: the cold `openurl` made **2 per launch**, and launches crashed in that
run; the launch above made **1 per launch and crashed 0 of 10**. The
`--initialUrl` argument is read at process start and loaded with an early
return, before both the last-opened entry and the baked default, so it is one
load by code and not by timing; `--terminate-running-process` is what makes
every launch the cold one that reads it. It is a launcher internal rather than
a documented API, so pin its statement with a test over the installed vendor
source, which goes red when an upgrade moves it; `/tooling-index` carries that
test's row where the install has one. **Counting BUNDLE requests cannot show
the double load**: the dropped host is replaced before it fetches the bundle, so
both forms fetch it once
(measured 2026-09-23 from per-launch process logs; the bundle request goes to
Metro directly, not through a proxy that fronts only the URL you launched with).
The manifest fetch (`HEAD /` then `GET /` with `expo-platform: ios`) is the
per-load signal.

Do this before **every** capture and **every** test run rather than once per
session: it makes your serve the launcher's most recent entry only until anyone
else on the box opens theirs.

`simctl launch` printing `<bundle id>: <pid>` proves a process, not a load (SKILL.md
trap 5), and the launcher falls back to the launcher screen when the serve is slow
to answer, so read the launcher's own recently-opened registry back. The entry
with the newest `timestamp` is what the client took, and its `url` names the port.
**The entry reaches the plist on disk late** - measured ~8 s after the
timestamp it carries (2026-09-23) - so a read straight after the launch sees the
PREVIOUS state and reads as "it did not take". Poll it, and count only an entry
stamped after the launch started:

The registry is the key `expo.devlauncher.recentlyopenedapps` in the app's own
preferences plist, inside its DATA CONTAINER:

```bash
PLIST="$(xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data)/Library/Preferences/$BUNDLE_ID.plist"
plutil -p "$PLIST"
```

**`xcrun simctl spawn "$UDID" defaults read "$BUNDLE_ID" ...` is NOT that read
and cannot substitute for it**: it addresses the simulator's global defaults
domains, where this app's domain does not exist, so it answers *"domain does not
exist"* for a client whose registry is full - an answer that reads exactly like
"the client opened nothing" and is not distinguishable from it - measured on
iOS 26.5, 2026-09-14. The same holds for every key in this app's preference
domain, not just the registry.

Two other instruments corroborate it, and neither is redundant - the registry
says which serve the client ASKED for, these say what it is running.
**Metro's own output** (section 4.1): the `iOS Bundled ... (N modules)` line and
the app's `LOG` lines travel the Metro websocket, so they cannot appear on a
machine the app is not attached to. And a **bundle marker only the intended
serve carries** - a testID or string the branch introduces, measured ABSENT from
every other serve on the box - observed in the running client.

**A SCREEN deep link (`$SCHEME:///<route>`) is neither of these**: it opens
that route in whatever bundle is already loaded, so it can never re-point one
(SKILL.md trap 9).

### 4.1 Proving it loads from YOUR stack, and not from a cloud one

This is trap 5's positive evidence for this loop, and it is **two** claims, not
one: the JS came from your Metro, and the app is talking to your backend. A
build made before the stack was up, or from a different worktree, satisfies
neither while looking completely healthy - it renders, it navigates, and it is
pointed somewhere else.

- **The JS**: Metro's own output prints `iOS Bundled ... (N modules)` as the app
  attaches, and the app's own `LOG` lines follow on the same terminal. Those
  travel the Metro websocket, so they cannot appear on a machine the app is not
  attached to - which is what makes them conclusive and the `Bundled` line
  alone not (section 4a.2).
- **The backend**: where the app logs the backend base URL it will call at
  startup (an app run on a device should), that line is the check. Against a
  local stack it is a `http://<host>:<port>/...` on the serving machine, the
  port being the backend's entry in `build.ports_artifact`; against a cloud
  environment it is the provider's own domain, and **that difference is the
  whole check**. The install's `CONTEXT.md`
  names that log line, the later line that corroborates it on a local build (a
  call answered by a local emulator), and the build-time entry that carries the
  ports a build was actually given, for when the host is right and you suspect
  the port slot instead.

## 4a. Remote: a non-Mac host driving the simulator over SSH

**The operator's machine is not a Mac, and the simulator only exists on one.**
This section is the loop for that: Metro and the backend stack stay on the
operator's host, while the build, the install, the launch and the simulator all
happen on a Mac over SSH. It is section 4 with the two halves on two machines,
so everything above still applies and only what the split changes is written
here.

**Why the split is not free.** The Metro host is compiled INTO the native shell
(SKILL.md trap 4), so the build has to be TOLD which machine is serving; a dev
script and a build script that each resolve "the host" as "my own address" are
right only on one box. **That rule is not restated here.** It belongs to the
install's scripts, which state it where each machine meets it - a cross-machine
usage example read before anything starts, the build's refusal on the building
machine, the serving banner's handover line on the machine that resolved the
address - and the install's `CONTEXT.md` names those places. **Read it
there**: a copy in this file is one more place for it to drift from.

What section 4a adds on top of that rule is everything the SSH layer brings and
the dev script has no reason to mention: how the tree reaches the Mac, why the
build refuses it, what a non-interactive shell does to the toolchain, and how a
capture is stopped from another machine.

The values: `ios.remote.host`, `ios.remote.user` and `ios.remote.workdir` name
the Mac and the directory to work in on it; `metro.host_cmd` asks the serving
machine for the address it serves on, which must agree with what the dev script
prints in its own banner. **The banner is the authority**; `metro.host_cmd` is
how to get the same answer without starting a stack.

### 4a.1 Setup: once per machine pair

Six things, each with the one-line proof that it is done. Run the proofs; a
setup step believed rather than measured is the one that fails inside a long
cold build.

| # | What | Prove it |
|---|---|---|
| 1 | **SSH key auth, non-interactive**, from the serving host to the Mac, and the Mac's key in `known_hosts` | `ssh -o BatchMode=yes <remote> true; echo $?` prints `0` |
| 2 | **A working directory of your own** on the Mac, at `ios.remote.workdir` | `ssh <remote> 'ls -d <workdir>'` echoes the path |
| 3 | **The repo, in that directory** | `ssh <remote> 'ls <workdir>/<repo>/package.json'` echoes it |
| 4 | **Dependencies installed there** | `ssh <remote> 'ls -d <workdir>/<repo>/node_modules'` echoes it |
| 5 | **A build credential reaching the build CLI on that Mac** | the build CLI's own `whoami`, run over `ssh` in `<workdir>/<repo>`, prints an account name rather than a login prompt (the install's `CONTEXT.md` has its exact command) |
| 6 | **The URL scheme pre-approved** on the simulator you will use (section 3) | the plist read-back in section 3, run over `ssh` |

`installation/check ios` collapses 1 into one command **and does it from the
non-Mac host**: with `ios.remote.host` set it probes the SSH prerequisite plus
the remote Xcode and device list in a single round trip, and its success line
names what it covered. **It deliberately does NOT cover step 5**, and says so in
the line, because a credential supplied per-invocation through the SSH
environment leaves nothing on the remote's disk to measure - a probe would be
measuring the wrong machine at the wrong moment. Step 5 is proved by hand, once.

**The placeholders in this section, because `<...>` promises a config key at the
top of this file and half of these are not one:**

| in 4a | is |
|---|---|
| `<remote>` | `<ios.remote.user>@<ios.remote.host>` - the Mac, written short because it appears in every command |
| `<workdir>` | `ios.remote.workdir`, a path ON THE MAC |
| `<serving host>` | the machine running Metro, from the dev script's banner or from `metro.host_cmd` |
| `<port>` | the Metro port, from `build.ports_artifact` / `build.metro_port_key` |
| `<repo>` | the checkout's directory name inside `<workdir>`. **Not a key** |
| `<login shell>` | the Mac's login shell. **Not a key** - see below |
| `<automation actor>` | a name and address for the snapshot commit's author. **Not a key** |
| `<UDID>` / `<identity>` | as in sections 3 and 4: from `simctl`, and from `--dry-run` |

**`<login shell>` in the commands below is not decoration.** A non-interactive
`ssh <host> '<cmd>'` reads none of the profile files, so it gets a bare PATH with
none of the toolchain on it (4a.3, first entry). Every remote command in this
section therefore runs through the Mac's login shell, and the shell's NAME is
machine state - ask the machine rather than writing it here.

**On step 1, `BatchMode=yes` is the load-bearing flag and belongs in every
command of this loop.** Without it, a host that has lost its key falls through
to a password prompt, and every command hangs with nobody present to type into
it: a missing key then presents as a wedged machine rather than as a missing key.

**On step 3, do not assume the Mac can clone.** A build machine often has no
forge CLI, no SSH key for the forge and no git credential helper, and then
`git ls-remote` fails with `could not read Username for ...: Device not
configured`. Push the tree from the serving host instead, which needs no
credential at all and carries the UNCOMMITTED edit you are actually testing:

```bash
rsync -az --delete \
  --exclude '/.git' --exclude 'node_modules/' --exclude '/ios/' --exclude '/android/' \
  --exclude '/.expo/' --exclude '/.env' \
  ./ <remote>:<workdir>/<repo>/
```

**`/.env` is in that set because the serving host's `.env` may be LIVE.** A dev
script that materializes `.env` per invocation and deletes it on teardown
leaves, at the instant of the rsync, a file describing ONE running stack - that
machine's host address and that worktree's port slot. Syncing it plants a stale
env file on the build machine, in the very tree the build archives. A build
script that re-materializes `.env` before reading it, in a repo that gitignores
`.env` so it never reaches the snapshot commit or the archive, absorbs that -
but neither property belongs to the sync, and a stale local override shipping
one machine's emulator URLs into a cloud bundle is the failure it would cause.
Exclude it, and do not rely on the two properties that happen to absorb it.

**An exclude also protects the file from `--delete`, so one already synced
stays until it is removed by hand.** After adding the exclude, remove it once on
the build machine - `ssh <remote> '<login shell> "rm -f <workdir>/<repo>/.env"'`
- or the sync keeps a file it no longer updates, which is worse than the one it
was updating.

**Anchor every directory exclude with a leading `/`.** An unanchored
`--exclude 'ios/'` matches a directory of that name at ANY depth, so it also
strips a nested `ios/` - a config plugin's `plugins/ios/`, say - that the build
genuinely needs, and `--delete` removes it if a previous sync had put it there.
See 4a.3.

**On step 4, the remote install is the app root only.** The build runs there and
runs nothing else, so the secondary dependency roots that a full gate needs are
not needed on the Mac. (This is the one place that differs from the per-worktree
install rule in `/worktree-workflow` section 1.3, and only because nothing on the
Mac ever runs a gate.)

**And the tree must be a git repository**, because the build CLI's local build
archives the project through git and refuses a directory that is not one. It is
a throwaway snapshot, not history:

```bash
ssh <remote> '<login shell> "cd <workdir>/<repo> && \
  git init -q -b snapshot && \
  git -c user.name=<automation actor> -c user.email=<automation actor> add -A && \
  git -c user.name=<automation actor> -c user.email=<automation actor> commit -q -m snapshot"'
```

**Because the archive comes from git, an rsync alone is invisible to the
build.** Every re-sync is followed by `git add -A && git commit` in the same
breath, or the build compiles the tree as it was at the last commit while the
files on disk say otherwise - a stale build that reports success. **Stamp the
snapshot commit with an automation identity, not a person's**: nobody made this
commit by hand.

### 4a.2 The normal use case: checking a UI change

Metro here, build there, then edit and look. Steps 1 to 4 are once per session;
step 5 is the loop.

```bash
# 1. SERVE, on your own machine. Foreground; background it in a
#    non-interactive session. Its banner prints the host it resolved, and the
#    banner is the authority on it.
<build.dev_script> up <build.dev_client_service> --env <env>

# The same address without reading the banner back - this is what
# metro.host_cmd is for, and it is the value you pass to the build in step 4:
<metro.host_cmd>

curl -s http://<serving host>:<port>/status   # -> packager-status:running
```
The port comes from the running stack's port artifact (`build.ports_artifact`,
key `build.metro_port_key`), never from this document: parallel worktrees each
hold a different port slot, and a port read from prose points the build at a
neighbour's stack.

```bash
# 2. Confirm the Mac can actually reach that Metro. One curl, and it is the
#    cheapest possible answer to "is the network up in the direction I need".
ssh <remote> 'curl -s --max-time 5 http://<serving host>:<port>/status'
#    -> packager-status:running
```

```bash
# 3. SYNC (4a.1 step 3) and COMMIT the snapshot (4a.1). Seconds, not minutes,
#    after the first time.

# 4. BUILD, INSTALL and LAUNCH, on the Mac. HOST_IP names the SERVING host.
#    If anyone else may have a simulator booted there, use the shimmed form
#    in 4a.3 instead - this one installs onto the first booted simulator.
ssh <remote> '<login shell> "cd <workdir>/<repo> && \
  HOST_IP=<serving host> <build.script> ios --env <env> --method <build.method_metro> \
  --target simulator -y"'
```
Add `--dry-run` first when you need the identity and the scheme: it prints
`identity=` and `scheme=` and builds nothing (SKILL.md trap 3). Run it ON THE
MAC, so the paths it prints are the ones that will exist.

**What it prints when it is right**: the build ends on a banner naming the
simulator UDID it installed to and the Metro URL it was pointed at. On the
SERVING machine, Metro's own log is the proof the bundle came from there:

```
iOS Bundled <ms>ms <the app's entry file> (<N> modules)
 LOG  [<the app's own startup logs>]
```

**The app's `LOG` lines arriving on the serving machine are the conclusive
half, not the `Bundled` line.** They travel the Metro websocket, so they cannot
appear on a machine that is not the one the app is attached to. A `Bundled` line
alone is consistent with a bundle served to something else.

```bash
# 5. THE LOOP. Edit JS on your own machine. Nothing else.
#    Fast Refresh delivers it to the simulator on the Mac in seconds, with no
#    rebuild, no reinstall, no re-sync and no re-commit: Metro is reading YOUR
#    working tree, and the snapshot on the Mac is only ever the native shell.
```

**That last sentence is the payoff of the whole arrangement**, and it is easy to
miss: the rsync/commit dance of 4a.1 is a NATIVE-shell concern. Once the shell
is installed, the JS you are iterating on never goes near the Mac's copy.
So the re-sync is owed only for the things that need a rebuild at all -
`technical/hot-reload.md`'s table, reached from section 5: a native module,
native config, an `EXPO_PUBLIC_*` key, the env, the Metro host - and every one
of those needs step 4 again anyway.

**Re-running without a build** is section 4's table, over `ssh`. The one you
want most - the pointing launch, which reloads YOUR serve rather than whichever
was opened last:

```bash
ssh <remote> "xcrun simctl launch --terminate-running-process <UDID> <identity> \
  --initialUrl http://<serving host>:<port>"
```

**Capturing what you are looking at** is section 6 unchanged, with one thing the
split adds: **you cannot `Ctrl-C` a recorder across `ssh`**, so record the
recorder's pid on the Mac and signal it by pid.

```bash
ssh <remote> "nohup xcrun simctl io <UDID> recordVideo --codec h264 <workdir>/out.mov \
  > <workdir>/rec.log 2>&1 < /dev/null & echo \$! > <workdir>/rec.pid"
# ... do the thing you are recording ...
ssh <remote> "kill -INT \$(cat <workdir>/rec.pid); \
  for i in \$(seq 1 15); do kill -0 \$(cat <workdir>/rec.pid) 2>/dev/null || break; sleep 1; done; \
  cat <workdir>/rec.log"
scp <remote>:<workdir>/out.mov .
```
**`nohup ... &` inside an `ssh` command is not optional**: the SSH session
ends when the command returns, and a recorder that is still a child of it dies
with the session, taking the unfinalized file with it. Wait for the process to
go before copying, exactly as section 6 requires locally - the difference is
only that here you cannot `wait` on a pid in another machine's shell.

**What to measure on this loop**, and the install's `CONTEXT.md` records the
numbers for its own app and link (the transport between the two machines is a
per-install choice; `metro.host_cmd` is what keeps its name out of this file):
the first rsync of the source tree and every one after it; the dependency
install on the Mac; the cold build, install and launch (the build CLI's own
install, prebuild, `pod install`, xcodebuild); the first bundle served across
the link; an edit on the operator's machine to the app's log line coming back
from the simulator; a relaunch with no build; and copying a recording back.
Measured 2026-09-04 on an Apple-silicon Mac over an overlay network rather than
a LAN, the shape is the one that matters: **the cold build and the first
dependency install on the Mac are the steps measured in minutes, both once per
setup, and the loop you actually work in - edit to log line, or a relaunch - is
the same seconds-long loop as a local one.**

### 4a.3 Gotchas and pitfalls

Each is a constraint plus the symptom it wears, because every one of them
presents as something other than what it is.

- **A non-interactive `ssh <host> '<cmd>'` gets a BARE PATH.** It is not a login
  shell and reads none of the profile files, so the toolchain a human sees on
  that Mac is simply absent. **Symptom**: `command not found: node` (or `npm`,
  or the forge CLI) on a machine where they demonstrably work when you log in.
  **Constraint**: run every remote command through a login shell, or set PATH
  explicitly. Do not "fix" it by hardcoding a version-numbered interpreter path
  into this loop - that path is machine state, and it moves.
  This is the same class as a CI runner's environment: what a job gets is not
  what your terminal gets, and validating in the terminal proves nothing about
  either.

- **The rsync carries the serving host's LIVE `.env` unless you exclude it.**
  **Symptom**: none, which is the problem - a stale env file describing one
  machine's host and one worktree's port slot sits in the build tree, and the
  only thing keeping it out of a bundle is a build script that overwrites it
  first. **Constraint**: `--exclude '/.env'` (4a.1 step 3). **And an exclude
  protects the file from `--delete`**, so one synced before the exclude existed
  stays forever, updated by nothing: remove it once by hand. Same class as the
  credential entry below - a build Mac is often shared, and a file left on it
  outlives the job that put it there.

- **An unanchored rsync directory exclude matches at every depth.**
  **Symptom**: the build dies in prebuild with a config plugin reporting a
  source file missing that is present and committed on the serving machine.
  **Constraint**: anchor directory excludes with a leading `/`. An unanchored
  `--exclude 'ios/'`, meant to skip the generated top-level native directory,
  also deletes a nested `plugins/ios/`.

- **The build CLI's local build refuses a tree that is not a git repository.**
  **Symptom**: `It looks like you haven't initialized the git repository yet.`
  followed by `Input is required, but stdin is not readable` - which reads as a
  broken pipe or a hung prompt rather than a missing `.git`. **Constraint**:
  4a.1's snapshot repo.

- **It archives the project THROUGH git, so uncommitted files do not exist to
  it.** **Symptom**: worse than a failure - a green build of the previous
  content, with your change simply absent from the app and nothing anywhere
  saying so. **Constraint**: commit after every sync.

- **The credential is a per-install decision, and it must not silently become a
  per-machine leftover.** A build credential has to reach the build on the Mac,
  and there are two channels: an environment variable named by
  `ci.eas_token_env`, passed for that one command, or a session on the Mac's own
  disk. The install's `CONTEXT.md` records which one it uses and why.
  **Constraint**: whichever is chosen, a credential placed on the remote for a
  one-off is deleted when the job is done and the deletion is verified, not
  assumed - a build Mac is often also where CI runners keep their checkouts.

- **A build Mac is where somebody else's simulator is most likely to be
  booted, and the build script installs onto the first booted one** (section
  4). **Symptom**: the build's banner names a UDID you did not boot, and the
  pointing launch leaves your own simulator empty. **Constraint**: section 4's
  shim, over `ssh`, in your own `<workdir>`, first on PATH inside the login
  shell:

  ```bash
  # the SHIM block from section 4, saved locally as xcrun-shim
  ssh <remote> 'mkdir -p <workdir>/xcrun-shim && cat > <workdir>/xcrun-shim/xcrun \
    && chmod +x <workdir>/xcrun-shim/xcrun' < xcrun-shim
  ssh <remote> '<login shell> "xcrun simctl boot <UDID>; xcrun simctl bootstatus <UDID> && \
    cd <workdir>/<repo> && PATH=<workdir>/xcrun-shim:\$PATH SIM_ONLY_UDID=<UDID> \
    HOST_IP=<serving host> <build.script> ios --env <env> --method <build.method_metro> \
    --target simulator -y"'
  ssh <remote> 'rm -rf <workdir>/xcrun-shim'
  ```
  `simctl boot` exits non-zero on a device that is already booted, which is why
  it is followed by `;` and the `bootstatus` wait by `&&`.

- **The serving host must be named to the BUILD, and its absence does not look
  like a missing flag.** **Symptom**: the build refuses
  `--method <build.method_metro>` for want of a reachable Metro (SKILL.md *The
  two scripts*), which reads as "start a dev stack" while the dev stack is up
  and healthy on the other machine. The refusal is right about the rule and
  wrong about your situation. **Constraint**: the dev
  script's cross-machine rule, above - this entry exists to name the SYMPTOM,
  because that is the part the rule's own home does not tell you how to
  recognise.

- **The Metro port is per worktree slot.** **Symptom**: everything connects and
  you are looking at a neighbour's code. **Constraint**: read it from
  `build.ports_artifact` (SKILL.md trap 2).

- **Scheme approval is written while the device is SHUT DOWN** (section 3), and
  over `ssh` there is nobody to dismiss the dialog if it is not. **Symptom**:
  `openurl` (or a flow's `openLink`) exits 0 and nothing opens. The pointing
  launch (section 4) opens no URL and does not need it.

- **The app can be in the background by the time you look.** **Symptom**: the
  first screenshot after a successful build is the home screen, which reads as a
  failed install. **Constraint**: assert on the consequence, not the exit code
  (SKILL.md trap 5); the pointing launch (section 4) brings it back on your
  serve. A bare `simctl launch` brings it back too, but on whatever bundle was
  opened last on that device - which is yours only while no other serve has been
  opened since.

- **THE REMOTE MAC MAY BE RUNNING SOMEBODY ELSE'S JOBS.** A build machine
  usually is one, and then your build is a second tenant of its CPU and of every
  cache the dependency manager keeps per USER rather than per checkout.
  **Symptom**: a build that fails inside dependency installation with a
  filesystem error on a lock or cache file, at a step that has nothing to do
  with your change. **Constraints**:
  1. **Work in `ios.remote.workdir` and nowhere else.** Anything that checks out
     on that machine may check out over its own directories at any moment.
  2. **Look before a long build**, with whatever tool lists that machine's
     in-flight jobs - and note it may not be INSTALLED on the remote, so run it
     from wherever it is.
  3. **Never clear a shared cache to unstick your own run**, which sabotages
     whatever build is using it beside you.
  4. **Classify a failure by PHASE before believing it.** An infrastructural
     death during dependency installation and a genuine resolution failure
     arrive at the same step with the same exit code, and reading the first as
     the second manufactures a permanent verdict out of a transient neighbour.

  **What else runs on that machine is a per-install fact and is NOT written
  here**; the install's `CONTEXT.md` records it, along with where the full
  account of any cache race the install has already paid for is kept. This file
  names no machine (SKILL.md's opening rule), and contention is the place that
  rule is easiest to break.

## 5. Proving hot reload

Platform-neutral, so it lives in `technical/hot-reload.md` beside this
file: the probe that works, what a refresh does NOT cover, and the order to
check things in when one does not arrive.

## 6. Screenshots and video

Both work with no visible Simulator window.

```bash
xcrun simctl io "$UDID" screenshot out.png
```

```bash
# recording: SIGINT is the stop, and it finalizes the file
xcrun simctl io "$UDID" recordVideo --codec h264 out.mov & REC=$!
sleep 5; kill -INT $REC; wait $REC
```

Verified 2026-09-03: the recorder prints `Recording completed. Writing to
disk.`, exits **0**, and writes a finalized QuickTime file (`ftyp`/`qt` with a
`moov` index). **`Ctrl-C` is an interactive habit that does not transfer to a
non-interactive shell** - send the signal deliberately and `wait` for the
process, or you race the write to disk. `--codec hevc` is the default; `h264` is
the safer choice for anything that has to be opened elsewhere.

**Under host load a recording's frame timestamps do not track the app's
timeline**: a phase can read ten times too long or hundreds of times too short
while the total is preserved, so a duration read off a recording is wrong in
either direction. Time it from the app's own timestamped log, and treat a
normal frame count spread over an abnormal duration as the sign.

`xcrun simctl io <udid> enumerate` lists the displays if `--display` is ever
needed; with one display the default is right and the tool says which it picked.

What a capture **owes a UI report** is not this skill's call: the install's UI
evidence gate owns that, and the install's `CONTEXT.md` records whether a
simulator capture satisfies it.

## 7. Input: taps come from a driver, not from `simctl`

**`simctl` cannot tap, swipe or type.** Its `ui` subcommand sets UI *options*
(appearance, content size), not input. So unlike Android
(`technical/android.md` section 4) there is no first-party command, and a tap
has to come from a driver.

| Route | What it costs |
|---|---|
| **Maestro** | installs its own XCTest driver onto the simulator at run time. **Nothing in the Xcode project**, which is what makes it viable where there is no checked-in project (below) |
| **`idb`** - `idb ui tap <x> <y>` | a companion daemon per simulator, and a dependency outside the Xcode toolchain. Coordinates only: element lookup and waiting are yours to write |
| **An XCUITest target** driven by `xcodebuild test` | a real test target in the project, and a build per run |
| **AXe** - `axe tap --id <testID>` / `-x <x> -y <y>`, `axe swipe`, `axe describe-ui` | one self-contained release tarball unpacked in your own workdir, no daemon and no XCTest, so it runs while Maestro's driver cannot attach (Xcode's pending first launch). About 300 ms per step (AXe 1.8.0, measured 2026-10-16), so it cannot place two taps closer than that |

The install's choice of driver is `device_e2e.driver`.

**AXe's `type` and `key` (HID keyboard events) switch the simulator into
hardware-keyboard mode, and the software keyboard stops appearing.** A focused
field then shows a caret and no keyboard, so no keyboard height reaches the app
and every keyboard bug becomes unreproducible. Measured 2026-10-16 on iOS 26.5
with AXe 1.8.0. Two things make it a void run rather than a visible failure:
- **The accessibility tree still lists the keyboard's keys in that mode**
  (`describe-ui` still returns a `space` element), so a check that reads it
  reports "keyboard up" while nothing is on screen.
- **A shutdown and boot of the device does not clear it**, and neither does
  setting the device's `HardwareKeyboardLastSeen` preference to false; a freshly
  created device does.
So enter text by TAPPING the on-screen keys (coordinates from a screenshot of
the keyboard), never with `type` or `key`, and confirm "keyboard up" from a
screenshot.

**In a project that generates `ios/` with prebuild and gitignores it, there is
no checked-in Xcode project**, so the third route needs a config plugin before
it needs a test. That single fact is what makes a driver that installs itself at
run time the cheap route there, and it is worth knowing before proposing the
others.

**`osascript` is not a route.** Driving the Simulator window through System
Events needs macOS Accessibility permission: it **prompts interactively**, and
without the permission the call fails with `execution error: ... is not allowed
to send keystrokes. (1002)` - measured 2026-09-03. A CI agent has nobody to
grant it, so a job depending on it does not fail loudly, it fails at a dialog
nobody sees.

**A tap-driver is for TESTS, not for the operator loop.** A step the loop itself
needs is still **removed rather than automated**: that is why the URL scheme is
pre-approved instead of the dialog being clicked (section 3), and why the
first-run sheet is addressed by a preference instead of by pressing Continue
(section 8). Reaching for the driver to dismiss a dialog is the wrong tool - it
makes every run depend on a JVM and a driver install to get past something that
should not be there.

### The device e2e suite

Where the install has one, `device_e2e.runner` is its route through all of
this, and what such a runner owes is: resolve a booted simulator, check the
stack the build loads from, run the flows in `device_e2e.flows_dir` with
`device_e2e.driver`, record the run to video (section 6), and collect the
artifacts. Where it points the app the selected flows drive at that stack, it
does so with the pointing launch of section 4 and refuses to run a flow if the
load is not proven; the install's `CONTEXT.md` says on which platforms its
runner points. **It points one app or none**: the app id comes from the flows'
own `appId:`, and when the selected flows name more than one it points none and
says so, because one serve cannot be right for two identities - run one flow per
identity to pin each. `/tooling-index` has the
runner's row, and `/e2e-suite` owns what a change owes it in coverage; the
install's `CONTEXT.md` names what its runner adds beyond this (another
platform, a per-flow check over the screenshots a flow took).

**From a non-Mac host it runs ON the Mac**, against the Metro served from the
operator's machine: sync the tree to a directory of your own under
`ios.remote.workdir` (4a.1 step 3, plus whatever dependency install the
selected flows need), then run the runner there over `ssh`, through the login
shell, naming the SERVING worktree's host and Metro port and the simulator's
UDID; the install's `CONTEXT.md` has the invocation. The serving host and port
are named because the tree on the Mac serves nothing and its own port artifact
describes no stack. A runner that points the app does so at that Metro itself;
by hand it is the pointing launch, never `simctl openurl` (section 4). Copy the output
directory back with `scp -r`.

Things a device run establishes that are worth knowing here:

- **A flow matches on `testID`s, not on coordinates**: a React Native `testID`
  surfaces as the accessibility identifier on iOS, so flows stay stable across
  layout changes. Verified 2026-09-03 against a running dev build.
- **Do not use Maestro's `clearState` on a dev-client build.** It wipes the
  saved Metro URL along with app data, so the next launch lands on the
  dev-launcher screen and every assertion fails for a reason unrelated to the
  app.
- **The Simulator has no camera**, so camera-backed screens render empty, and a
  web suite's fake camera feed does not reach a native build, so flows assert on
  navigation and chrome rather than on a frame (`technical/camera.md`).
- **Anything about the keyboard needs the SOFTWARE keyboard on screen, and
  "Connect Hardware Keyboard" suppresses it.** With the Simulator's I/O >
  Keyboard > Connect Hardware Keyboard on, a focused field raises no on-screen
  keyboard, the app receives no keyboard with a height, and every keyboard
  defect class - a sheet lifted off the screen, a field left under the
  keyboard, an offset frozen mid-hide - is simply absent, while the flow that
  was meant to reproduce it passes. Measured 2026-09-24, iOS 26.5: with
  Simulator.app NOT running, a simulator booted by `simctl` showed the
  software keyboard although the global `com.apple.iphonesimulator
  ConnectHardwareKeyboard` default was 1; the per-device setting lives under
  `DevicePreferences.<UDID>.ConnectHardwareKeyboard` in the same domain and is
  what Simulator.app applies when it IS running. **Do not trust a preference
  read: before any keyboard run, prove the keyboard is up** - a screenshot, or
  the hierarchy carrying `inputView` (`maestro hierarchy`). A keyboard check
  that finds no keyboard on screen issues NO VERDICT, never a pass, for exactly
  this reason.
- **The dev client's floating TOOLS BUTTON takes taps meant for the app, and
  no selector can route around it.** It is drawn in its own window over the
  top-right of the screen, and it is NOT in the view hierarchy, so a `tapOn`
  by id of an app control under it lands on it and opens the dev menu instead.
  Switch it off once per device in the dev menu (Tools button); the setting
  persisted across launches on both the simulator and an Android emulator
  (measured 2026-09-24), so the trap and the fix are the same on Android.

## 8. Observed failures

**`Unable to locate the executable cmake` is NOT a missing build tool, and
installing cmake makes things worse rather than better.** It is what an upstream
artifact-hosting problem looks like from here. `pod install` decides
prebuilt-vs-source by `curl -I -L`-ing three React Native iOS tarballs; when they
are not retrievable - Maven Central has served them 404 intermittently while
their sibling `.pom` and `.sha1` returned 200 (observed 2026-09-09) - React
Native does not fail: it
**silently reverts to building itself and Hermes from source**, and
`Pod::Executable::which!('cmake')` is called at exactly one site in all of
react-native, inside that from-source podspec branch. The log line just above
it is the tell:

```
[ReactNativeDependencies] No prebuilt artifacts found, reverting to building from source.
[Hermes] Using the latest commit from <version>-stable.
[!] Invalid `hermes-engine.podspec` file: [!] Unable to locate the executable `cmake`.
```

**Install cmake and you trade a loud failure for a silent one.** A from-source
React Native is **static**, while Expo's precompiled xcframeworks expect the
dynamic one, so a build that gets past pod install installs and then crashes at
launch:

```
dyld: Library not loaded: @rpath/React.framework/React
      Referenced from: .../Frameworks/ExpoVideo.framework/ExpoVideo
```

It also turns the prebuilt build into a far longer from-source Hermes build on a
machine meant to do neither, and it does nothing about the outage.

**Probe with `curl -L` if you go looking:** Maven Central 301s these `.tar.gz`
paths to `https://repo.reactnative.dev/maven2` (measured 2026-09-09), so a probe
without `-L` shows `301` and reads as a different fault entirely.

**A build script can turn this into an early, loud refusal**: preflight those
three URLs, redirect to a path-compatible Maven Central mirror when the base in
effect is missing any of them, and, if no base serves all three, refuse the
build with a message naming both consequences - rather than letting the
operator discover the first as a missing tool minutes later and the second on a
device. The install's `CONTEXT.md` says whether its build script does and names
the preflight's escape hatch; `/tooling-index` has its row.

**The first-run developer-menu sheet MAY cover the app on first launch.** When
it appears it reads *"This is the developer menu ... Continue"*, and it does
**not** block the bundle load or Fast Refresh - the app is running behind it - it
only ruins a screenshot. Its preference key is `ios.dev_menu_onboarding_key`.

**It is a MAY in both directions, so do not plan a run around it in either
direction.** Measured 2026-09-09, a fresh install-and-launch produced **no
sheet at all**: the first screenshot after the install was the app's own screen.
A run that budgets a step for a sheet that is not there costs the same as one
surprised by a sheet that is, and the preference being present says only that
some earlier run wrote it - never that this build shows the sheet.

**The way to know, on the device and the build in front of you, is leg 1 of the
control below.** A screenshot that matches what you expected is not a
measurement of this.

**There is no `simctl` route to dismiss it** (section 7). The only manual
route is the dev menu's own toggle - Control-Command-Z, or Device > Shake -
which needs a visible `Simulator.app` window and a hardware keyboard, i.e.
exactly the two things a headless or remote run does not have. A UI-automation
tap on Continue (below) is the route that works headlessly; the preference does
not.

**The preference belongs in the app's own preferences plist inside its DATA
CONTAINER** - section 4's `$PLIST`, which is the only file the app reads. Create
it if it is not there yet, set the key, then terminate and relaunch:

```bash
# $PLIST as set in section 4 - an unset one silently makes every line below a no-op
[ -n "$PLIST" ] || { echo "PLIST unset"; return 1 2>/dev/null || exit 1; }
[ -f "$PLIST" ] || plutil -create binary1 "$PLIST"
plutil -replace <ios.dev_menu_onboarding_key> -bool true "$PLIST"
xcrun simctl terminate "$UDID" "$BUNDLE_ID"; xcrun simctl launch "$UDID" "$BUNDLE_ID"
```

`plutil -p "$PLIST"` is the read that sees what the app sees (section 4).

**This recipe does NOT suppress the sheet on the dev client.** Measured
2026-10-06 on an iOS 26.5 simulator, on a dev-client build: the key was set in
the container plist with the app terminated, the app was relaunched, and the
sheet appeared anyway. An appearance after the key is set is decisive in a way
an absence is not. What does work headlessly is a UI-automation tap on its
**Continue** button (Maestro); that opens the full developer menu, which needs a
second tap to close before the app is visible.

**`xcrun simctl spawn "$UDID" defaults write "$BUNDLE_ID" ...` cannot do this
job**, for the same reason the matching `defaults read` cannot do section 4's:
it addresses the SIMULATOR-GLOBAL preferences domain rather than the app's
sandbox container, so the value lands in a plist the app never reads and the
write silently does nothing. Measured 2026-09-14 on an iOS 26.5 simulator, in
both directions: one dev-client build's container plist HAS
`<ios.dev_menu_onboarding_key>` while `simctl spawn ... defaults read "$BUNDLE_ID"`
answers *"does not exist"*, and for a second build of the app the container
LACKS the key while a `simctl spawn ... defaults write` of it lands in the
global plist.

**What would make it provable is removing the human, not repeating the
observation.** A person present at the same window could have dismissed the
sheet, so the measurement that settles it is the one where **no such actor
exists**, and it needs all three legs:

1. **A control on the same device and the same build**: with the preference
   ABSENT from the app's preferences plist (section 4 has the read), terminate
   and relaunch, and record whether the sheet is there. **This leg does two
   jobs and has THREE outcomes, not two.** Sheet PRESENT: the treatment in
   leg 2 is measurable, and this is the control that stops a sheet which had
   simply stopped appearing on its own from reading as a success. Sheet
   ABSENT: the negative control has passed, the instrument cannot tell
   suppression from a sheet that was never going to appear, and the run
   therefore issues **no verdict about the preference at all** - it is
   INCONCLUSIVE, never a green. Leg 1 not run: nothing below it may be reported
   either, for the same reason.
2. **The treatment**: write the preference into the container plist, read it
   back as `1` with `plutil -p`, terminate and relaunch - the sheet is gone and
   the app is visible.
3. **No alternative cause available**: the run is driven entirely over a
   non-interactive SSH session with no operator, and **no tap driver is
   installed** (section 7 - with neither Maestro nor `idb` present there is no
   route by which anything could have pressed Continue).

**Keep leg 1 and leg 3 if you ever re-measure this, and keep leg 1's absent
branch as an INCONCLUSIVE rather than collapsing it onto pass or fail.** Leg 2
alone produces a result that looks identical to the real one and proves nothing,
and with the sheet a MAY it will produce that result by itself sooner or later. A
check whose control is dropped for tidiness keeps passing and stops being able to
fail.

**The tap driver can segfault SpringBoard.** Observed once, 2026-09-03 on iOS
26.5 / Xcode 26.6: an `EXC_BAD_ACCESS` in
`-[XCTAutomationSession initWithAccessibilityFramework:dataSource:]`, i.e. the
driver's XCTest session attaching to the accessibility framework - not the app.
macOS raises its own crash dialog for it, because a simulator's processes are
HOST processes; the dialog is real and it is not about your Mac's own
SpringBoard. **The simulator recovers on its own**: SpringBoard restarted, the
device stayed booted, and the app under test kept running. No crash of that
signature predated the driver's install on the machine it was seen on, which is
what attributes it to the driver. Treat it as a cost of the driver, not a fault
in the app, and do not go looking for it in a flow's assertions.

**`SIGTRAP` at start-up is the DOUBLE LOAD, and the pointing launch does not
cause it.** The app dies seconds after a cold start, at its first Fabric mount,
with `EXC_BREAKPOINT` in a Swift `_assertionFailure` under
`ExpoFabricView.injectInitializer`; the process log says
`ExpoFabricView.swift:197: Fatal error: The app context has been lost`
(expo/expo#48575, open with no fix as of 2026-09-23).
macOS raises its own crash-reporter dialog for it. The cause is two React hosts
initialising at once: expo-modules-core caches the Fabric view classes for the
process with an initializer that holds one host's context weakly, and when the
DROPPED host injects last, the surviving host's first mount finds it gone. The
two hosts come from a cold `simctl openurl` of the dev-client URL on a build
whose baked default launcher URL is a live Metro (section 4). Measured
2026-09-23 on one simulator and one build, 10 cold launches each: the cold
`openurl` crashed in that run, the pointing launch
(`simctl launch --terminate-running-process ... --initialUrl ...`) **0 of 10**,
and a bare `simctl launch` is one load by code as well.

So the recovery is the pointing launch, which also puts the client back on YOUR
serve. A bare `simctl launch` recovers it too, but on the last-opened bundle
(section 4). The report is at `~/Library/Logs/DiagnosticReports/<app>-*.ips`; its
first line is JSON metadata and the remainder is a second JSON document, and the
simulator's UDID appears in it, which is how a report is attributed to one
simulator on a Mac running several. **What this does not cover**: a warm
reload of a running app still replaces its host, and overlapping reloads are
expo/expo#48653's family (a `jsi::Pointer` `EXC_BAD_ACCESS` after a long
session), not this one.

**The build script launches through the pointing launch** (SKILL.md *The two
scripts*), and so does `device_e2e.runner` where it points the app (the
install's `CONTEXT.md` names the one implementation): the pointing launch plus
the registry proof of section 4, failing loudly when the client records no load
of the requested Metro. The consequence it keys on is
the registry, never `simctl launch`'s exit status (SKILL.md trap 5); `simctl
spawn <udid> launchctl list` does name a running app as `UIKitApplication:<bundle
id>` on iOS 26.5 (measured 2026-09-23: 1 while running, 0 after the crash), which
is the check for a crash after the load was recorded.
