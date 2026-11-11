# signin_driver - the hands for the automated sign-in

A long-lived stealth headful Chromium behind a unix socket, plus a one-shot client.
It performs exactly the command it is handed and reports what it sees. **It decides
nothing.** SKILL.md step 6 owns the procedure; this file is the command reference.

> **There is no `sign-in` command, and there must never be one.** A script of
> this flow fails on its own model of the screens rather than on any block: Google
> moves the form into a popup, so a Next clicked on the opener lands on nothing, and
> a screen the model never reaches, such as Anthropic's Authorize button, has no
> step.
> Screens, labels and element ids change. The agent inspects the page it is on and
> chooses from what is there - that is what makes this route survive a redesign, and
> a helpful `sign-in` command would throw it away.

## Install

```
cd <the agent-revive skill directory>/signin_driver
npm ci                                  # 44 packages, pinned by package-lock.json
PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers" npx playwright install chromium
```

`installation/check --online` does both and verifies them; on a fleet host,
`fleet install` and `fleet upgrade` do them in the host checkout. `node_modules/`,
`browsers/` and `run/` are gitignored; nothing here is committed but source.

**The driver points itself at `browsers/`** - it sets `PLAYWRIGHT_BROWSERS_PATH`
itself (which is why it imports playwright *dynamically*: a static import is hoisted
above every statement, and Playwright reads that variable while its registry module
evaluates). So it works launched by hand, by the client, or from anywhere else, and
it does not depend on the caller's shell happening to have the variable exported.
With no chromium under `browsers/` it exits **2** naming the one command to run,
rather than dying as a Playwright stack trace in a log the client only points at.

Needs `node` and, on a Linux host with no X session, `xvfb-run` - the browser runs
**headful**, because headless is rejected by Google at the identifier step
("This browser or app may not be secure"). A virtual display satisfies headful.
On macOS the browser draws through WindowServer, which a user has only while
logged in at the console (the Aqua session, launchd's `gui/<uid>`), so `start`
never uses xvfb-run there, and a unix socket path holds 103 bytes instead of 107.
`share` additionally needs `x11vnc`, `websockify`, noVNC and a `tailscale` that may
run a Funnel on `share.funnel_port` (the install's `config.json`); `installation/check` runs each.
`share` is Linux only: x11vnc shares an X11 display, and on macOS `share` exits 2
naming SKILL.md step 7e, the human route.

## Commands

Every call takes the agent name first. The client prints one JSON reply and exits.

```
node signin.mjs <agent> start [--config P] [--run-dir D] [--log F] [--no-xvfb]
                             [--pool-file P] [--profile <username> [--port N]]
                             [--app-window]
node signin.mjs <agent> pages
node signin.mjs <agent> inspect [--page N]
node signin.mjs <agent> goto <url> [--page N]
node signin.mjs <agent> click --role <role> --name <text> [--page N] [--exact]
node signin.mjs <agent> click --text <text> [--page N]
node signin.mjs <agent> click --selector <css> [--page N]
node signin.mjs <agent> fill  --label <text> --value <text> [--page N]
node signin.mjs <agent> fill  --label <text> --secret <username> [--page N]
node signin.mjs <agent> press --key <key> [--page N]
node signin.mjs <agent> wait  [--ms N] [--page N]
node signin.mjs <agent> shot  --name <slug>
node signin.mjs <agent> savecode
node signin.mjs <agent> quit
node signin.mjs <agent> share [--minutes N] [--config P]
node signin.mjs <agent> unshare [--config P]
node signin.mjs profiles-check [--profile <username>] [--config P] [--pool-file P]
```

- **`inspect`** is the one you live in: the page's visible text plus every visible
  interactive element with its role, label, text and disabled state. It is what lets
  an agent act on a screen nobody has seen before.
- **`pages`** matters more than it looks. Google moves the sign-in into a **popup**,
  so from the "Continue with Google" click onward the page to act on is index 1, not
  0. Re-read `pages` after any click that could open or close a window.
- **`--secret <username>` passes a USERNAME.** That account's password is read from
  the account pool *inside the driver process* and typed straight into the field.
  There is no way to pass a password through the client, deliberately: nothing that
  records - a command line, a shell history, a tool result, a transcript - ever
  holds it.
- **`savecode` prints a file path and a length, never the code.** Paste it with
  `tmux send-keys -l -- "$(cat <file>)"`. Its JSON comes AFTER the driver's log
  lines on stdout, so piping the whole output into a JSON parser yields nothing; the
  file is always `<run_dir>/code.txt` (the `run_dir` that `start` printed) - paste
  from that path when the parse fails, inside the same minute.
- **`shot` is for a screen you cannot understand, not for the callback page.** A
  PNG is the one channel the redactor structurally cannot reach: the OAuth code is
  ordinary visible text on that page, so a shot puts it on disk in pixels and opening
  the file puts it in a transcript. Shots are written mode 0600 and die with the run
  dir, which bounds the exposure rather than removing it.
- **`--pool-file P`** overrides which pool file is loaded, instead of
  `accounts.pool_file`: a test fixture, or an agent's own credential file, which
  holds ONE `{ username, password }` object and is read as a one-entry pool. It
  changes which passwords the browser can type, so it is not a convenience.
- **`--profile <username>`** opens that pool account's **stored profile** instead of a
  throwaway one (below). The username must be in the pool and a single path segment.
  A profile another browser holds is refused with exit **2** and `profile in use`,
  checked on Chromium's own `SingletonLock` BEFORE a browser is launched - a launch
  on a held profile opens a stray window in the browser that holds it, which on a
  live sign-in shifts `pages` under the agent driving it (measured; `profile.mjs`).
- **`--port N`** (with `--profile` only) opens Chromium's DevTools on
  `127.0.0.1:N`, for the designated owner to enroll a profile over ssh, on request;
  every other enrollment shares an `--app-window` driver instead (SKILL.md, "Stored
  profiles"). `start` then
  prints `person_steps` - the ssh tunnel, `chrome://inspect`, Configure
  `localhost:N`, inspect the page target and, once it opens, the Google popup's - and
  `port_answers`, read from the port itself. The tunnel is
  `ssh -L N:127.0.0.1:N <login>@<Tailscale name>`, the name read from
  `tailscale status`: a laptop cannot resolve the bare hostname. Every local
  process can reach that port while the driver runs: quit once the profile is signed
  in.
- **`--app-window`** makes the first window an app window - no tabs, no address bar,
  no menu - on a `data:` start page, and records the driver's `DISPLAY` and
  `XAUTHORITY` in the run dir (`display.json`). `goto` works in it as in any window.
  A `window.open()` popup from it (Google's sign-in) has no address bar either; a
  `target=_blank` link opens a normal tabbed window. Without the flag nothing about
  the browser or the run dir changes.
- **`share`** (tap-to-solve, SKILL.md step 7) shows that window to ONE person:
  `x11vnc` on the driver's Xvfb (127.0.0.1, a one-time password in `vnc.pass`, mode
  0600), `websockify` serving noVNC (127.0.0.1), and a Tailscale Funnel on
  `share.funnel_port`, all from `share.*` in the install's `config.json`. It prints ONE JSON
  object - `url`, `password_file`, `expires_at` - and **never the password**, and arms
  a detached teardown at `--minutes` (default `share.minutes`). The person can move
  the pointer and LEFT-click (a left-drag included) and nothing else: no right,
  middle or wheel button, no keyboard, no clipboard either way - enforced by
  `x11vnc`'s own flags, which `share.mjs` names one by one, including `-safer` (no
  remote control that could widen them) and `-nevershared` (one viewer at a time, a
  reconnect replacing the old session). It refuses (exit 2) a driver not started
  `--app-window`, a display other than the Xvfb the driver's own `xvfb-run` started,
  and a driver with more than one window open, and (exit 1) while a share is live or
  being set up on this host (one is set up at a time per VNC port), or its ports are
  taken; every readiness check asks whether the share's OWN process holds the
  listener on 127.0.0.1, the address websockify and the funnel connect to. A failure
  half-way is torn down, from the record in memory, before it exits.
- **`unshare`** turns the funnel port off FIRST and confirms it from Tailscale's
  status, then kills the share's processes (each one only after its command line
  proves it is the share's, escalating to SIGKILL because `x11vnc` can hang on
  SIGTERM), deletes the password, kills the expiry timer LAST, and prints what it
  did. Safe to repeat. A teardown that cannot finish exits 1 with `clean: false`
  and keeps the record and the timer, which are what retry it; the driver's `quit`
  then keeps only the record and its log, and the next `start` there refuses until
  `unshare` clears it. With nothing recorded in this run dir but the funnel port
  still serving, it says so and exits 1 rather than turning off a share it does not
  own. The tailscale command always comes from config (or `AGENT_REVIVE_TAILSCALE`),
  never from the record, and a run dir that is not a 0700 directory of this user is
  not read at all.
- **`profiles-check`** reports each stored profile (or the one `--profile` names)
  as ONE JSON object: `claude` and `google` each `in`, `out` or `unknown`, read
  from where `https://claude.ai/` and `https://myaccount.google.com/` land, or a
  `status` of `busy`, `absent` or `error`. It launches the driver on each profile
  with no port, sends it `goto`, `wait` and `quit` and nothing else, and never
  creates a profile: an absent one is reported, not launched. `unknown` is a real
  answer - an interstitial or an unread landing - and never means `in`.
- **`start` removes a STALE socket by itself.** A socket file is not a living driver:
  after a SIGKILL the file remains, and treating it as alive would leave `start`
  refusing and `quit` unable to connect - a deadlock, arriving after /login has
  already blocked a live agent's pane. So `start` probes the socket and unlinks a
  corpse.

## What it resolves, and from where

`--agent <name>` names the run dir and nothing else. The passwords come from the
**same account pool the picker reads** - `accounts.pool_file` in the install's `config.json`,
relative paths against that file's directory - so the account SKILL.md step 5 names
is looked up in the file it was picked from. Any agent may be signed in with any pool
account. `pool.mjs` is the one reader of that file: it hands back passwords in-process
and its errors name the path and the defect, never a byte of the file - V8's
`JSON.parse` quotes the text around a syntax error, and the driver's start-up log is
the one stream nothing redacts.

## What it leaves behind: the run dir never, a stored profile on purpose

Every run has a **run dir** under the system temp dir - the socket, the shots, the
code file, and with `--app-window` the display record and any share's state, log and
password - and it is removed when the driver quits or is signalled, in both modes.
The **profile** is the difference between them:

| | throwaway (no `--profile`) | stored (`--profile <username>`) |
|---|---|---|
| where | `<run dir>/profile` | `<accounts.profiles_dir>/<username>` |
| after `quit`, a crash, a signal | removed with the run dir | **kept** |
| mode | 0700 (the run dir's) | 0700 on the profiles dir and the profile, re-set on every start |

**Either way the profile is a credential, and that is why each mode treats it as
it does.** After a successful sign-in a profile holds live Google and claude.ai
sessions for the pool account. Its cookies are encrypted with Chromium's fixed
built-in key, not a keyring (Playwright launches with `--password-store=basic`), so
anyone who can read the directory can sign in as that account. The throwaway one is
therefore deleted, so a revival leaves nothing a later reader could sign in with.
The stored one is kept because a browser Google and claude.ai already know types no
password - and is kept ONLY in `accounts.profiles_dir`, beside the pool file: the
driver refuses a `profiles_dir` that resolves (symlinks included) into a git work
tree or under an agents home, because a profile there is a standing impersonation of
that account. There is no flag that takes a profile path. Never point `--run-dir`
at a repository, an artifact directory or an agent's home either.

Cleanup is wired to `quit`, to `exit`, to SIGINT/SIGTERM, and to an uncaught
exception or unhandled rejection - so a crash removes the run dir too, and never a
stored profile. A live share is torn down first, by the same `stopShare` `unshare`
uses, because its record is in the run dir. **A SIGKILL or a reboot cannot be
covered by anything**: after one, the run dir survives and must be removed by hand -
**after** `unshare` (or a new `start` on that run dir, which tears a recorded share
down before it wipes), because a share outlives a SIGKILLed driver until its timer
and its only record is in that dir. It is mode 0700, which is what
bounds that window. A stored profile's session reaches disk when `quit` closes the
browser cleanly; `profiles.test.mjs` restarts a profile and reads its cookie back.

The driver's **log** lives outside the run dir, on purpose - it is the evidence when
the driver never starts, which is exactly when the run dir does not exist - so `quit`
does not remove it. It is created mode 0600, and the client scrubs `DEBUG`,
`PWDEBUG` and friends from the child's environment, because `DEBUG=pw:api` makes
Playwright log every call's arguments (the password among them) straight into it,
where this module's own redaction has no say.

## Tests

```
node redaction.test.mjs
node profiles.test.mjs
node share.test.mjs
```

`profiles.test.mjs` guards the stored profile and the throwaway mode beside it, on a
fake pool, a fake config and a temp profiles dir, loading only `about:blank`,
`data:` URLs and a server it runs on `127.0.0.1`. Its half A is pure (`profile.mjs`'s
rules, the driver's refusals, structural checks); its half B runs real drivers and
needs this directory's `node_modules`, a chromium build and a display or `xvfb-run`
(~40 s). It pins: a profile kept by `quit` while the run dir goes, a cookie that
survives a restart on a stored profile and not on a throwaway one, the modes, a busy
profile refused before Chromium with no stray window in the holder, `profiles-check`
end to end, the throwaway mode's replies key for key, and no pool password on any
output or driver log, nor in any file of the profile it was typed into. A host
without half B's needs gets exit **3 NO VERDICT**, never a pass.

`share.test.mjs` guards the share, with a FAKE `tailscale`
(`../fixtures/fake-tailscale.mjs`, through `AGENT_REVIVE_TAILSCALE`) and a tripwire
`sudo` and `tailscale` first on `PATH`, so nothing it runs can make anything public.
Its half A proves the input restriction on a throwaway Xvfb: a minimal RFB client
sends a left, right, middle and wheel click, a chord, a left-drag, two keys and
clipboard text each way, and `xinput test-xi2 --root` reports what reached X -
first through a CONTROL `x11vnc` without the restriction, which must deliver all of
it, then through the share's own arguments, which must deliver the left button and
the drag and nothing else. Half A also sends side buttons 6-8, tries
`x11vnc -R input:KMBC` from outside the session (against a control without
`-safer`, where it works), and opens a second viewer. Its half B runs real drivers:
the refusals without `--app-window`, with two windows open and on a display the
driver's own `xvfb-run` did not start, the app window read off the screen's own
pixels against a tabbed control, `share`, a second `share` refused, `unshare` twice,
the expiry timer, a funnel that fails to come up, a funnel that fails to turn OFF (by
`unshare` and by `quit`: record and timer kept, `start` refusing), two shares racing,
and teardown on `quit`, on SIGTERM and by the next `start` after a SIGKILL, with no
one-time password on any output. Exit **3 NO VERDICT** when a control misbehaves or a
half cannot run (~75 s).

`redaction.test.mjs` runs offline, with no browser and no `node_modules` - which is why `redact.mjs`, `wire.mjs` and
`pool.mjs` import nothing but node builtins, and why the test asserts that they do.
It pins that a password and an OAuth code cannot leave through any reply path,
**including the error path**, that a malformed pool file is refused without its
bytes in the message (against a control proving the raw parser message DOES carry
them), that the driver reads the pool through `pool.mjs` only, that a password is
matched literally rather than as a regex, that
it is matched in its **JSON-escaped on-wire form** as well as raw, and - structurally
- that every socket write in `driver.mjs` goes through the one redacted wire. It
exits **3 NO VERDICT** when a control misbehaves; 3 is not a smaller pass.
