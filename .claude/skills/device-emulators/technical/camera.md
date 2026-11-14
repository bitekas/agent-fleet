# The camera on a simulator or emulator

What a virtual device can and cannot tell you about a camera bug, for an app
using `expo-camera`. Every measured fact carries its date and platform, because
that is a re-check trigger.

## 1. There is no camera, and what that means per platform

| | iOS Simulator | Android AVD |
|---|---|---|
| capture device | **none** | a virtual one (VirtualScene / emulated) |
| the preview view mounts? | **yes** - `<CameraView>` mounts and its `onCameraReady` fires (~50 ms after mount, measured 2026-09-03, iOS 26.5) | yes, with a rendered 3D room in it |
| what the empty preview looks like | **nothing of its own**: the preview layer is transparent until a frame arrives, which on a simulator is never, so the feed region shows whatever the app paints UNDER `<CameraView>` (measured 2026-10-14, iOS 27.0 simulator) | the virtual scene |
| a capture | a **synthetic black JPEG with a date/time stamp**, the same shape as Android's (measured 2026-10-06, iOS 26.5 simulator, dev client) | a **synthetic black JPEG with a yellow timestamp**, by expo-camera design; where an install recorded how it established this, its `CONTEXT.md` cites it |
| permission | headless: `simctl privacy` (section 3) | headless: `adb shell pm grant` |

**On the iOS Simulator the feed's COLOUR cannot tell a mounted preview from
an unmounted one.** The preview layer paints nothing, so a mounted-but-empty
preview shows the app's ground - the same colour any placeholder the app paints
in that slot shows. Whether the JS put the native view there is answered by the
app's own log line (`onCameraReady`, section 5's method) or by the view
hierarchy (the driver's hierarchy dump), never by luma. That is the half of a
"black camera" report a simulator CAN adjudicate. What it cannot see is the
other half: a native capture session that mounted and delivers no frames. A
device run that shows black WITH the preview mounted and ready is that case, and
no simulator result bears on it. **State which half a simulator verdict covers,
every time.**

**The same transparency is a phone-visible defect class, not a simulator
quirk.** On a phone the layer stays transparent for the few hundred milliseconds
the session takes to deliver its first frame, so whatever is painted under the
preview IS the first thing the user sees of the camera, on every mount; the
install's `CONTEXT.md` names where the app pins that ground, if it does.
Android's `PreviewView` is opaque black until its first frame, so the ground
does not show there (measured 2026-10-14 on an API 36 AVD).

**An Android emulator cannot show a STALE frame across a camera switch,
so it cannot adjudicate a "flash of the previous camera" report.** On a phone
the PreviewView (PERFORMANCE mode, a SurfaceView) keeps the previous bind's
last frame until the new stream's first frame lands. On the headless
swiftshader AVD that gap is black, or the new stream is already live under a
short fade: six flips each on a virtualscene/emulated pair showed no old
frame, both on stock expo-camera and on a build that lifted its own cover
before the new stream started (measured 2026-09-23). What the emulator CAN
adjudicate is the ORDER of events. Log `CameraState` and
`PreviewView.previewStreamState` natively and compare them with the JS-side
reaction.

## 2. Measuring the feed instead of looking at it

`luma.py` beside this skill reads a region of a `simctl`/`screencap` PNG and
prints its mean luma, with no image library. Two regions per screenshot: the
feed, and a region known to be black (chrome), so the reader is calibrated on
every run and a broken reader cannot pass as a dark feed.

```bash
python3 "${CLAUDE_SKILL_DIR}/luma.py" shot.png                  # feed + calibration region, defaults
python3 "${CLAUDE_SKILL_DIR}/luma.py" shot.png --feed .1,.9,.22,.55 --cal .3,.5,.90,.97
```

**Calibrate on every screenshot, not once.** A reader that decodes wrongly -
a lossy format conversion on the way in is enough - can report a known-black
navigation bar at 168, the same value as a light-grey feed, and nothing in a
single "feed = 170" number reveals that. The known-black region is what makes
the feed number mean anything, and it costs one extra line.

## 3. Permissions, headlessly

The iOS permission dialog is a tap nobody can perform on CI (`technical/ios.md`
section 7). Pre-grant, or reset to test the undetermined path:

```bash
xcrun simctl privacy "$UDID" grant camera "$BUNDLE_ID"
xcrun simctl privacy "$UDID" reset camera "$BUNDLE_ID"     # back to undetermined
```

VERIFIED 2026-09-03 in both directions, read back from the simulator's TCC
database (`data/Library/TCC/TCC.db`, `auth_value` 2 = allowed). Android:
`adb shell pm grant <package> android.permission.CAMERA` (UNVERIFIED).

## 4. Putting the app in a known state without tapping

**Per-run state lives in the app container, and it is editable while the app is
terminated.** An AsyncStorage-backed flag - a first-run carousel's "seen" flag,
an intro's completion - is a key in
`<container>/Library/Application Support/<bundle id>/RCTAsyncLocalStorage_V1/manifest.json`,
found with `xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data`.

**iOS: TERMINATE FIRST, THEN EDIT, THEN LAUNCH - THE MANIFEST IS CACHED IN
MEMORY.** The native module holds the whole manifest in memory and flushes it on
exit, so a key deleted from `manifest.json` while the app is running is invisible
to the running app AND overwritten when it exits. Measured 2026-09-03: a flag
removed under a running app was back on the next launch, and a flow that depends
on the removal then fails on an assertion screens later, which is where nobody
looks for a storage race. **The edit is not "unreliable" - it is discarded**, so
retrying it under a running app fails identically every time.

**Android is NOT the same, and assuming it is costs a launch each time.**
AsyncStorage there is a SQLite database, not a JSON manifest, and the row can be
deleted while the app runs:

```bash
adb -s "$SERIAL" shell "run-as <identity> sqlite3 \
  databases/RKStorage \"DELETE FROM catalystLocalStorage WHERE key='<key>';\""
```

The app's in-memory copy is still stale, so the change lands on the next read
rather than instantly - but nothing overwrites the delete. Where a flow only
needs the key gone by the NEXT screen, no terminate is required.

**State the platform whenever this is written down.** "Delete the key before
launch" is right on both and wastes a relaunch on Android; "the key can be
deleted live" is right on Android and SILENTLY WRONG on iOS, where it produces a
green edit, a stale app, and a failure screens later.

This is how a cold-start loop lands on the screen under test every time instead
of on whatever the last run left behind.

## 5. The N-cold-starts method

An intermittent fresh-start bug is chased with a loop, and the loop's evidence is
the app's own log lines - a screenshot alone says black, not why.

1. Instrument the candidate transitions with a tagged `console.log` (Fast
   Refresh delivers it, no rebuild) and **revert it in the same session**.
2. Per run: terminate, note the Metro log's line count, launch, wait, screenshot,
   slice the log from that count, score the run from the slice.
3. Print one row per run: which transitions occurred, in which order, with the
   latency between them. Ten identical rows with tight latencies is a result;
   so is one row that differs.

Write the latencies down with their date and platform where the install keeps
such measurements: a device is the only place they can be different, which is
the point of writing them down.

**One operator per simulator.** A person using the same simulator during the
loop changes the screen under the run - carousel page, navigation state, a modal
- and the run scores their interaction, not the app. Such runs carry no
evidence either way and must be reported as such, not as failures.

## 6. Onboarding flows are not stable anchors

A carousel remembers its page across launches, a sign-in sheet shows once per
session, a hint pill's text changes after the first capture. Flows that assert on
those pass on the run they were written against and fail on the next. Assert on
`testID`s the screen carries for exactly this purpose, and on structure
(the preview slot present / not present) rather than on copy.
