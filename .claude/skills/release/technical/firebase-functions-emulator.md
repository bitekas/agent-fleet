# The Cloud Functions for Firebase emulator as a release-regression server

Vendor facts behind `SKILL.md` section 6 for an install whose backend is Cloud
Functions for Firebase and whose section 6 server is the functions emulator
(`firebase emulators:start --only functions`, from firebase-tools) pointed at
the live project. `SKILL.md` section 6 states the requirement in terms any
serverless runtime meets; this file says how this runtime behaves under it.
A fact carries the date or the tool versions it was measured on where one was
recorded, and that is when to re-check it: after any firebase-tools or
firebase-functions major, re-read the source files named in sections 1 and 2
(firebase-tools' `lib/emulator/functionsEmulator.js`, firebase-functions'
`lib/common/providers/https.js`).

## 1. What it serves against a live project, and what it does not

Read 2026-09-04, from two sources of different strength.

- **The documentation enumerates the supported background-trigger sources, and
  every entry is an emulator.** That is a positive enumeration, not a stated
  negative, so it does not by itself say a cloud event cannot arrive.
- **The negative comes from firebase-tools' emulator source**: each background
  trigger registration (Firestore, Realtime Database, Auth, Storage, Pub/Sub) is
  gated on the corresponding emulator's registry entry and delivered by that
  emulator, and no registration path targets a cloud project's event stream.
  That source (`lib/emulator/functionsEmulator.js` and the registry it
  consults) was read on `master`, not on a pinned build.
- **HTTPS callables (`onCall`) and `onRequest` routes are the one class with no
  such gate**: they are always served, at a real local URL,
  `http://127.0.0.1:<port>/<project id>/<region>/<function name>`.

So with no Firestore, Auth, Storage or Pub/Sub emulator running, the server
serves the callables and the HTTP routes and nothing else:

- **Firestore triggers, Storage triggers and scheduled functions keep running on
  the live deployment**, from the previously deployed code.
- **A scheduled function never fires in the emulator.** A schedule is
  registered only as a subscription on a Pub/Sub topic, only where a Pub/Sub
  emulator is running, and only an explicit publish to that topic invokes it.
- **An auth blocking function stays live.** The emulator writes its blocking
  configuration to the local Auth emulator only, so a real sign-in runs the
  deployed one.

**The startup log over-counts.** Auth and Storage trigger registrations report
the function as initialized (`auth function initialized`) whether or not
anything can ever dispatch to it. Firestore and database registrations print
that the function was ignored, naming the absent emulator, and so do Pub/Sub
registrations, which is what a schedule is. A census of what the server serves
therefore reads the log's `http function initialized` lines as served, its
`ignored` lines as not served, and its `auth function initialized` lines as not
served either. Any other line kind is unmeasured, not "not served": read the
source before counting it (a task-queue function, say, with the Cloud Tasks
emulator this mode starts). A boot census taken this way (2026-10-06) confirmed
the source reading: every Firestore and Pub/Sub trigger reported ignored, and an
Auth `user().onCreate` trigger reported initialized with nothing able to
dispatch to it. The census counts what the BOOTED source exports, not what the
live project has deployed, so it is re-taken on every release's boot.

**The served set cannot be narrowed per function.** A per-function
`--only functions:<name>` filter is a deploy-time feature: the emulator ignores
it and serves every function the source exports (established 2026-09-04). A
server of this kind therefore serves the whole request-driven surface, whichever
client each function was written for.

**Keeping emulator hosts out.** The Admin SDK reaches an emulator whenever its
host variable is set: `FIRESTORE_EMULATOR_HOST`, `FIREBASE_AUTH_EMULATOR_HOST`
and `FIREBASE_STORAGE_EMULATOR_HOST`. So a boot scrubs all three from the
emulator's environment, and generates the `firebase.json` it starts from with no
`emulators.firestore`, `emulators.auth`, `emulators.storage` or
`emulators.pubsub` block at all, so nothing can start one.

## 2. The callable channel does not verify ID tokens

Measured 2026-09-04, by sending a forged unsigned JWT to a callable on an
emulator pointed at a live project, which then performed a live Firestore read
as the uid in the token.

- **The emulator sets a debug feature that makes the functions SDK's `onCall`
  wrapper decode the bearer token without verifying it.** firebase-tools'
  `lib/emulator/functionsEmulator.js` starts every runtime with
  `FIREBASE_DEBUG_FEATURES={"skipTokenVerification":true,"enableCors":true}`,
  and firebase-functions' `lib/common/providers/https.js` then calls
  `unsafeDecodeIdToken` in place of `verifyIdToken`. The same feature disables
  App Check verification and identity-blocking verification. It is
  unconditional emulator behaviour and cannot be turned off without patching the
  SDK.
- **An `onRequest` route that calls the Admin SDK's `verifyIdToken` in its own
  code still verifies**: with no Auth emulator running, it checks real cloud ID
  tokens against the project the emulator was started with, and a token minted
  by a different project is rejected.

So every callable is reachable as any uid by anyone who can reach the server.
A callable whose identity check is `request.auth.uid` checks a value the caller
wrote.

## 3. Secrets

- **A secret is fetched lazily, per invoked function, never at boot.** The
  emulator resolves a function's declared secrets (`defineSecret`) from Secret
  Manager under the bound credential when that function is first invoked. A
  boot log with no secret line in it is the healthy case.
- **An unresolvable secret parameter reads as an empty string rather than
  throwing**, so the function runs and answers normally. The only signal is the
  emulator's own error block, whose text contains
  `Unable to access secret environment variables`. A wrong credential produces
  it, which is the negative control that proves a grep for it can match.
- **A callable's `onCall` wrapper rejects an empty body (HTTP 400) before any
  user code runs.** So a warm can `POST {}` to every callable that declares a
  secret: the worker starts and fetches its secrets, and no handler code runs.
  An `onRequest` route has no such wrapper; a warm calls one only where its
  handler has been read to reject a missing credential before touching data.
- **A local secrets file (`.secret.local` in the functions directory)
  satisfies the parameters from disk**, which disconnects a secret check from
  the credential it claims to measure: a check that finds one present reports
  INCONCLUSIVE.
- **`firebase-debug.log`, written at the project root, records every Secret
  Manager response, payloads included.** So a boot deletes a previous copy, and
  the teardown deletes this one and reports it.

## 4. The one-hour credential, and the worker that crashes the server

Measured on firebase-tools 15.25 through 15.31.

- **The CLI mints one access token from the service-account key when it starts
  and cannot refresh it under a key** (`apiv2.js` throws `TypeError: Cannot read
  properties of undefined (reading 'access_token')`). The first NEW function
  worker that fetches a secret after the token's hour takes the whole emulator
  down, and the emulator's own output then says only
  `An unexpected error has occurred.`: the real error is in
  `firebase-debug.log`, so a boot that sees the emulator exit should print that
  log's last `TypeError` / `Error:` lines before the teardown deletes it.
- **A worker keeps its secrets for its life.** A warmed function keeps its
  worker until a file under the functions source directory changes: the
  emulator watches it, and a change (a build, a pull, a test run) drops every
  idle worker, which the log flags as `FUNCTIONS RELOADED`. A second
  CONCURRENT call to a warmed function spawns a second worker. Either is a new
  worker, and past the deadline a new worker is the crash.
- So the deadline is boot plus a margin under one hour, a restart (a new CLI
  process, a new token) is the only reset, and a warm after the deadline would
  spawn exactly the workers that crash it.

## 5. Ports, the UI, and the warning that names no project

- **The Emulator UI starts under a functions-only run unless the generated
  config disables it** (`emulators.ui.enabled: false`; measured 2026-09-04: the
  banner printed the UI's address and its port was bound, and a boot with the
  flag off printed no banner and bound no UI port). Its committed port is
  usually a local development stack's. The hub, functions, Eventarc, Cloud Tasks and
  logging emulators each take a port too; give every one of them a fixed port
  outside every port a local development stack uses.
- **The CLI's warning that "calls to these services will affect production"
  names no project**, so it is identical whichever project the emulator was
  started against.

## 6. The client side of the override

- **`getFunctions(app, url)` with a URL as its second argument sets the
  instance's `customDomain`**, and every callable made through that instance
  then resolves to `${customDomain}/${name}`. With `url` set to
  `<server base>/<project id>/<region>`, that is exactly the emulator's endpoint
  for each callable. It moves the callables only: auth, Firestore and Storage
  keep the project configuration they were initialised with.
- **A raw `fetch` to an `onRequest` route reads its base URL from wherever the
  client code says** - usually a public environment key - so it moves only if
  the same override value reaches it too.
