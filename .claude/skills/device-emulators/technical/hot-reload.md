# Proving the hot reload

Platform-neutral: it is the same Metro websocket on iOS and Android, so this
lives in one file rather than twice.

## The probe

`touch` proves nothing - Metro keys on content, so a touch on an unchanged file
produces no output, which is indistinguishable from a broken watcher. Change
content, and put the evidence where Metro will print it:

```bash
printf '\nconsole.log("[hmr-probe] re-evaluated");\n' >> <a file the running screen imports>
# Metro prints:  LOG  [hmr-probe] re-evaluated
git checkout -- <that file>
```

**Module scope is the point.** Fast Refresh re-evaluates the changed module, so
a statement at module scope runs on refresh; one inside a function only runs if
something calls it, and its absence would then say nothing.

Measured 2026-09-03 (iOS Simulator): the line appeared within seconds of the
write, with **no rebuild and no reinstall**.

**Revert it in the same step you add it.** It is a live edit to a real source
file, and an unreverted probe is a debug log shipped to the landing branch.

## What Fast Refresh does NOT cover

A refresh replaces JS modules in a running native shell. Anything the shell
itself carries needs step 2 of the route again - a full build, install and
launch:

| Changed | Refresh enough? |
|---|---|
| JS / TS, styles, a component, a route | yes |
| a new dependency that is pure JS | yes, after Metro re-resolves it |
| a native module added or upgraded | **no** |
| native config: app identity, scheme, permissions, icons, splash | **no** |
| a config plugin - which is how every one of those is produced | **no** |
| an `EXPO_PUBLIC_*` key, or the env the build was made for | **no** - it is compiled in |
| the Metro host the build points at | **no** - also compiled in |

**The last three are the ones that mislead**, because the app keeps running
and serving a new bundle while pointing at the old backend. Nothing on screen
says the env is stale. If the app behaves as though it is talking to a
different environment than you think, suspect a build made for a different
`--env` before suspecting the code.

## When a refresh does not arrive

In order, cheapest first:

1. **Is Metro serving?** `curl -s http://<host>:<port>/status` must answer
   `packager-status:running`. The port comes from the stack's port artifact
   (`build.ports_artifact`), never from a document.
2. **Is the app connected to THAT Metro?** Its startup lines in Metro's own
   output are the evidence, and the launcher's recently-opened registry answers
   it without waiting for one - the newest entry's `url` names the port the
   client took (each platform file has the read). An app launched against a
   previous port keeps running happily and receives nothing, and on a box
   running several serves that port is routinely somebody else's (`SKILL.md`
   trap 9).
3. **Did the module actually change?** See the probe above.
4. **Reload the whole bundle** rather than debugging the diff: re-open the
   dev-client URL at your Metro and verify the registry took it (each platform
   file has both commands). A full reload is seconds and rules out
   refresh-boundary oddities that are not worth diagnosing. **A plain
   relaunch is not that**: it reloads the last-opened bundle, so if step 2 found
   the client on the wrong serve it comes back on the wrong serve (`SKILL.md`
   trap 9).
