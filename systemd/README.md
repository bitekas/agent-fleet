# systemd/ - the agent daemons

Every standing agent runs a scheduler and one watcher per working chat
transport as long-running user services. A Claude Code Monitor lives at most 30
minutes, so a daemon run as a Monitor's child is down from the kill until the
session re-arms it, with nothing to say so; a unit is not.

| | |
|---|---|
| Script | `systemd/agent-daemons.py` (follower, log rotation, launchd exec shim, job table, status, refresh, unit rendering, install) |
| Templates | `agent-sched@.service.in`, `agent-watch@.service.in`, `agent-daemons-refresh.service.in`, `agent-daemons-refresh.timer`; on macOS `agent-sched.plist.in`, `agent-watch.plist.in`, `agent-daemons-refresh.plist.in` |
| Units | `agent-sched@<agent>.service`, `agent-<watch.job>@<agent>.service` per working transport (Slack: `agent-slack-watch@<agent>.service`), `agent-daemons-refresh.service` + `.timer` |
| Test | `python3 systemd/agent-daemons.test.py` (offline: fake systemctl and launchctl, fake `/proc`, temp tree; in a macOS CI job, on the repository owner's own runner, also one real temporary LaunchAgent, booted out at the end) |
| Log | `<agents-root>/<agent>/state/daemons/<job>.log`; cursor `<log>.cursor` and follower lock `<log>.follow.lock` beside it |
| Runs as | the agents' user, user units (macOS: LaunchAgents), no root |
| Service manager | systemd, or launchd on macOS, through `lib/fleetlib/services.py`; this file describes systemd and the section [macOS: launchd](#macos-launchd) what differs |

In this file `<fleet>` is the fleet checkout and `<agents-root>` is
`agents_root` in the host settings (`~/.config/agent-fleet/host.json`, written
by `fleet install`).

## What runs

The jobs are `sched` plus one per working transport in the registry (every
`.claude/skills/*/transport.json` whose `status` is `working`). A transport job
takes every name from its descriptor's `watch` block:

| | scheduler | transport job |
|---|---|---|
| job | `sched` | `watch.job` |
| unit | `agent-sched@.service` | `agent-<watch.job>@.service` |
| script | `<fleet>/.claude/skills/scheduled-tasks/sched.py` | `watch.script` in the transport's skill directory |
| config file | `<home>/config/scheduler.json` | `<home>/config/<watch.job>.json` |
| config variable | `SCHED_CONFIG` | `watch.config_env` |
| follower filter | none | `watch.follow_include` |

For Slack that is `slack-watch`, `agent-slack-watch@.service`,
`config/slack-watch.json`, `SLACK_WATCH_CONFIG`, `state/daemons/slack-watch.log`.
A placeholder transport gets no job and no unit.

```bash
python3 <fleet>/systemd/agent-daemons.py jobs           # job, unit, script: one line per job
python3 <fleet>/systemd/agent-daemons.py jobs --json    # the table `fleet` reads
```

`jobs --json` prints the units' interpreter and, per job, its unit, script, log
and config file (both relative to the agent home), config variable, follower
filter and transport. `fleet pin-daemons` and `fleet status` read it from the
tree they work on, so the job list is written down here and nowhere else. It
runs without host settings; of them it reads only the optional `python`, the
interpreter `fleet install` records.

Per instance `%i` = agent, every path derives from the agent home
`<home>` = `<agents-root>/%i`:

- `WorkingDirectory` = `<home>/<project>`, the install checkout (the one
  directory in each agent home holding `.claude/fleet.json`), because a
  predicate may read a path relative to it.
- `CLAUDE_CONFIG_DIR=<home>/.claude` and the job's config variable, set **in the
  unit**, so they are in the daemon's `/proc/<pid>/environ`: the owner guards
  read `CLAUDE_CONFIG_DIR`, and the agents verify a daemon by reading it there.
- Optional per-agent tunables in `<home>/config/<job>.env` (`EnvironmentFile=`,
  `KEY=value` lines). A value there overrides the unit's `Environment=` lines,
  so the file carries tunables only, never the two paths above.
- stdout and stderr appended to `<home>/state/daemons/<job>.log`.

**Restart policy.** A crash restarts after 10 s, backing off to 5 min over five
restarts (`RestartSteps`), and never gives up (`StartLimitIntervalSec=0`).
**Exit 0 is not restarted** (`RestartPreventExitStatus=0`): the scheduler and
every watcher exit 0 only for a GUARD refusal (another copy holds the lock, or
`CLAUDE_CONFIG_DIR` is not the config's owner), and retrying that is a loop
that changes nothing. The unit then sits `inactive (dead)`, the GUARD line is in
its log, and the follower raises `DAEMON-ALERT`. A Monitor-run copy of a daemon
makes the unit exit at once: stop the Monitor first.

## The units are rendered, not linked

`render-units` writes the unit files from the templates in this directory:

```bash
python3 <fleet>/systemd/agent-daemons.py render-units --units refresh --out <dir>
python3 <fleet>/systemd/agent-daemons.py render-units --units all --out <dir>
python3 <fleet>/systemd/agent-daemons.py render-units --units all --list
```

- `--units refresh` renders `agent-daemons-refresh.service` and
  `agent-daemons-refresh.timer`. `--units all` adds `agent-sched@.service` and
  one `agent-<watch.job>@.service` per working transport.
- `--out <dir>` is the directory written into (created when absent);
  `fleet install` passes a temporary directory and puts the files into
  `~/.config/systemd/user` itself. `--list` prints the unit file names, one per
  line, and writes nothing: it is how a caller learns which units a render will
  replace.
- `--host-config <file>` is the host settings file every unit names as
  `FLEET_HOST_CONFIG`; without it, the file the render reads. `fleet install`
  renders before it writes anything, reading a candidate host.json in a
  temporary directory, and passes the file it writes: a unit naming the
  candidate would start its daemon against a file that is gone.
- It prints one `rendered <path> from systemd/<template>` line per file it
  wrote (`, replacing a link to <target>` when the path was a symlink), and
  `nothing changed` when every file was already identical. Exit 0 in both cases.
- **A file is replaced, never written through.** Each is written to a temp file
  in `<dir>` and renamed over the path, so a symlink at the path is replaced and
  the file it pointed at is left untouched.
- Every file is rendered before the first is written, so a fault leaves `<dir>`
  as it was. A placeholder without a value, a missing install checkout, and
  agent homes whose install checkouts have different directory names are
  environment faults (exit 3).
- It does not touch systemd. Keeping each unit's enabled state across the
  replacement (`disable` before, `daemon-reload` and `enable` after, so the new
  `.wants/` links name the rendered file) and starting the refresh timer are the
  caller's: `fleet install` does both.

Each rendered file starts with
`# Rendered by fleet install from systemd/<template> at <tag>. Edit the template, not this file.`,
where `<tag>` is `git describe --tags --always` of the fleet tree. Edit the
template and re-render; an edit to a rendered file is lost at the next render.

Template placeholders:

| Placeholder | Value |
|---|---|
| `@FLEET@` | the fleet tree `agent-daemons.py` runs from (`realpath`) |
| `@PYTHON@` | every unit's interpreter: `$FLEET_PYTHON`, else host.json's `python` (which `fleet install` writes from `FLEET_PYTHON`), else `/usr/bin/python3` (systemd) or `/opt/homebrew/bin/python3` (launchd) (`PYTHON` and `PYTHON_LAUNCHD` in `agent-daemons.py`, and `python` in `jobs --json`) |
| `@AGENTS_ROOT@` | `agents_root` from the host settings |
| `@PROJECT_DIR@` | the install checkout's directory name under each agent home |
| `@JOB@` | the job (`sched`, `slack-watch`) |
| `@SCRIPT@` | the job's script, absolute |
| `@CONFIG@` | the job's config file, relative to the agent home |
| `@CONFIG_ENV@` | the job's config variable |
| `@DESC@` | watch template: `<Transport> watcher (<watch.script>)` |
| `@ENV_PREFIX@` | watch template: `watch.config_env` without its `_CONFIG` suffix, naming the example tunable in a comment |
| `@HOST_CONFIG@` | the host settings file `--host-config` names, else the one the render reads (`FLEET_HOST_CONFIG`, else `~/.config/agent-fleet/host.json`), absolute; every unit and plist sets it as `FLEET_HOST_CONFIG`. `fleet install` reads a candidate in a temporary directory and names the file it writes, so no unit names a file that is gone when install returns |

A re-render on an existing host adds the `FLEET_HOST_CONFIG` line to its units
and restarts nothing: a running daemon takes it at its next start, which
refresh's daily restart brings within a day.

## The follower - what a session arms instead of the daemon

```bash
python3 <fleet>/systemd/agent-daemons.py follow <agent> sched
python3 <fleet>/systemd/agent-daemons.py follow <agent> slack-watch \
  [--include REGEX] [--exclude REGEX] [--replay-max M]
```

- Prints every complete log line it has not delivered, from the byte cursor in
  `<log>.cursor`; a line is printed and flushed **before** the cursor moves past
  it, so a follower killed mid-delivery repeats a line rather than losing one.
  Lines written while no Monitor was armed are delivered on the next arm.
- A partial line (no newline yet) waits until it is complete.
- No cursor: it starts at the end of the log (`--install` writes the cursor
  before the first start, so the first arm gets the unit's output from line one).
- A log shorter than the cursor (truncated) is announced in one `DAEMON-FOLLOW`
  line and read from 0. A rotated log's undelivered tail is drained from
  `<log>.1` first; a replaced log whose old file is gone is announced and read
  from 0, and the cursor keeps how far the old file was delivered (`replaced`),
  which refresh's salvage reads (see Refresh).
- **Filter.** `--include` / `--exclude` are Python regexes applied before
  anything is counted; a filtered line is consumed, never re-offered. A watch
  job with no `--include` uses its transport's `watch.follow_include`;
  `--include ''` turns the filter off. The scheduler has no default filter.
- **Backlog cap:** more than `--replay-max` (default 20) undelivered lines at once
  prints one `DAEMON-BACKLOG <unit>: N lines since <UTC time>, showing the newest M
  ...` header, then M lines in log order: the `--priority` lines first, the
  newest of the rest after them. The default priority is `SCHED due`,
  `SCHED alert`, each working transport's `<line_prefix> DM ` and `DAEMON-`;
  with Slack alone, `^(SCHED due|SCHED alert|SLACK DM |DAEMON-)`. The header
  names the log and the byte offset where all N are.
- About 10 s after an arm and every 60 s after that it reads the unit's
  `ActiveState`, `Result` and `NRestarts` and prints ONE `DAEMON-ALERT` line when
  the unit is not active or restarted on its own since the last check; while it
  stays down the alert repeats at most every 30 minutes; recovery prints one
  `DAEMON-OK`. Every new arm re-announces a unit that is down.
- One follower per log (flock on `<log>.follow.lock`); a second exits 0 with one
  `DAEMON-FOLLOW another follower already delivers ...` line.
- **It ends itself after `--max-secs` (default 1740 s, `0` = never)**, with one
  last line, `DAEMON-FOLLOW follow <agent> <job>: stopping after ... - re-arm the
  follower to keep receiving`, then exit 0. The Monitor harness kills its command
  at 30 minutes, and a line flushed into the pipe in the moment before that kill
  is never read while the cursor is already past it, so it is lost. A follower
  that exits first is read to EOF, and a line written after it stopped waits past
  the cursor for the next arm. Re-arm on that line or on the exit notice.

The script finds its tree through `realpath`, so it runs the same when invoked
through a symlink from another directory.

## Refresh - code changes go live, and a daily restart

`Restart=always` alone would keep a process running old code forever after an
upgrade, and keep a watcher's per-process state forever.
`agent-daemons-refresh.timer` runs `agent-daemons.py refresh` every 5 minutes.
For each **active** instance it reads the running process:

- the script: the first argument after the interpreter that is not an option,
  in `/proc/<pid>/cmdline`;
- the config file: the job's config variable in `/proc/<pid>/environ` (the
  agent's default config file when the variable is absent);
- `<home>/config/<job>.env`.

When one of them is newer than the process, or the process is over 24 h old
(`--max-age-hours`), the unit is restarted with `systemctl --user restart`,
after one `DAEMON-REFRESH restarting <unit>: <reason>` line is appended to its
log so the session reads why.

**A daemon writing to a replaced log is restarted too.** The unit opens its log
once, at start (`StandardOutput=append:`). A tool that rewrites the log in place
(`sed -i`, or any write-a-copy-and-rename) gives the path a new inode while the
daemon keeps appending to the old, unlinked one, and moving the log away keeps
it writing to the moved file: the follower then reads a file that never grows,
and the agent hears nothing with every unit active. So refresh also reads the
process's stdout and stderr (`/proc/<pid>/fd/1` and `2`) and restarts a unit
whose descriptor is a regular file other than the one at the job's log path,
with the reason `writes to a replaced log (<log>: the daemon's fd points at a
deleted inode)`. The `DAEMON-REFRESH` line goes into the file at the path, the
one the follower reads. A descriptor that is not a regular file (a pipe, a
socket, a terminal) is not judged. **A daemon log is written only by its unit:
never edit it in place, move, truncate or delete it; read it, or copy it.**

**What the daemon wrote to the replaced file is salvaged before the restart.**
Those lines are exactly the ones nobody heard, and the restart would free the
file. refresh reads it through the daemon's descriptor (`/proc/<pid>/fd/1`,
which opens a file with no name left) and appends to the file at the path,
before its `DAEMON-REFRESH` line, the lines nobody has, under one header:

```
DAEMON-SALVAGE <n> line(s) the daemon wrote to the replaced log <log> before this restart
```

They land after the follower's cursor, so its next pass delivers them once
(more than `--replay-max` arrive condensed, as any backlog does). The
`DAEMON-REFRESH` line ends `; salvage: <n> line(s)`, or `; salvage: none,
<why>`. What nobody has is worked out from the files: the replacing tool
usually copied the old lines into the new file, often edited, and the follower
delivered some of them before it lost the old file. The boundary is the new
file's last line where it occurs exactly once in the old file; else the old
file's first lines when the new file is exactly those lines, each the same or
a rewrite of it (its unchanged start and end hold half its characters, or the
words unchanged in place do); and never earlier
than where the follower left the old file (its cursor). An empty new file
(every line deleted, or the log moved away) leaves only the follower's place.
A log moved to `<log>.1` that the follower's cursor still names is the
follower's to drain, as after a rotation, so none of it is salvaged.
When none of that holds, nothing is salvaged and the line says `salvage: none,
boundary not found`. The rule, and where it can over- or under-include, is the
SALVAGE comment in `agent-daemons.py`. **A manual `systemctl --user restart`
skips the salvage and loses those lines; run `agent-daemons.py refresh`
instead.** One refresh runs at a time (a lock beside the refresh log,
`~/.local/state/agent-fleet/daemons-refresh.lock`): a second one, the timer's
while one runs by hand, prints `another refresh holds <lock>; this one does
nothing` and exits 0, so no line is salvaged twice. A lock it cannot make or
take (an unwritable state directory, a filesystem without locks) is reported,
and the run goes on without it. A dry run takes no lock.

Because the inputs come from the process, the
decision is right whether the unit runs the fleet's script, an install's copy or
a canary tree. A manual restart resets `NRestarts`, so a refresh raises no
alert. A unit that is down is left alone: that is the follower's alert, not
something to retry.

```bash
python3 <fleet>/systemd/agent-daemons.py refresh --dry-run
```

prints one `DRY-RUN restart|keep|skip <unit>: ...` line per daemon unit (a keep
line names the script and config it read; a restart for a replaced log ends
with the `salvage:` note, the number of lines it would salvage) and restarts
nothing and writes nothing.

A scheduler restart replays pending runs: the scheduler re-emits every pending
run older than its replay grace at start, with `replay=1`, so a fire nobody
acknowledged reaches the session again beside its original line. A replay never
advances the task or creates a run.

**Log growth.** `ExecStartPre` runs `agent-daemons.py rotate`, which moves a log
over 10 MB to `<log>.1` (one generation) at each start; the daily refresh restart
is therefore the latest a log is checked. `rotate` reads no host settings and
imports nothing from the fleet, so a broken install cannot keep a daemon from
starting.

## Install for an agent

The units must be rendered first (`fleet install --units all`). Then, for an
agent with `<home>/config/scheduler.json` and/or a transport's config file (a
job without its config is SKIPPED, saying so):

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
python3 <fleet>/systemd/agent-daemons.py --install <agent>    # timer, enable --now
systemctl --user status agent-sched@<agent> agent-slack-watch@<agent>
python3 <fleet>/systemd/agent-daemons.py --uninstall <agent>  # disable --now that agent's units
python3 <fleet>/systemd/agent-daemons.py --uninstall          # every instance, the timer, the rendered files
```

`--install` refuses (exit 2, nothing called) while a rendered unit is missing,
and for a name that is not an agent home.

## Look

```bash
systemctl --user is-active agent-sched@<agent> agent-slack-watch@<agent>
systemctl --user show agent-sched@<agent> -p NRestarts -p Result -p MainPID
tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value agent-sched@<agent>)/environ | grep -E '^(CLAUDE_CONFIG_DIR|SCHED_CONFIG)='
tail -n 50 <agents-root>/<agent>/state/daemons/sched.log
journalctl --user -u agent-daemons-refresh.service -n 20
```

Editing a template needs a re-render, `systemctl --user daemon-reload` and a
restart of the instances; editing `agent-daemons.py` needs nothing for
`rotate`/`refresh` and a re-arm for a running follower.

`systemctl --user` needs `XDG_RUNTIME_DIR`. A non-login shell (an agent's Bash
tool included) often has it unset, and every `systemctl --user` then fails with
"Failed to connect to user scope bus". `agent-daemons.py` sets it for its own
calls.

## Check an agent's daemons

```bash
python3 <fleet>/systemd/agent-daemons.py status <agent> [--json]
```

prints each job's unit, state, pid and restart count (`--json`: also its load
state, result, command line and log), and exits 1 when a job the agent has a
config file for is not active, or is `DEAF`: running, but writing to a replaced
log (see Refresh), so its follower delivers nothing; its row names the remedy,
`agent-daemons.py refresh`, which salvages before it restarts. `--json` carries that as
`log_replaced`: the reason (`writes to a replaced log (<log>: ...)`), `false`
when the output reaches the log, `null` when the job's stdout and stderr cannot
be read (the job is down, the process is another user's, or neither is a
regular file). `fleet status` and agent-revive's triage read it from here. It reads the service manager through the same
interface on both systems, so it is the check a boot message or a revive step
names, never a `systemctl` or `launchctl` line.

## macOS: launchd

On macOS the jobs are LaunchAgents in the user's launchd domain (`gui/<uid>`,
or host.json's `launchd_domain`), named by host.json's `launchd_prefix`
(default `com.agent-fleet`):

| | systemd | launchd |
|---|---|---|
| job unit | `agent-<job>@<agent>.service` | `<prefix>.<job>.<agent>`, file `~/Library/LaunchAgents/<label>.plist` |
| refresh | `agent-daemons-refresh.service` + `.timer` | `<prefix>.daemons-refresh` (`StartInterval` 300) |
| interpreter | `/usr/bin/python3` | `/opt/homebrew/bin/python3` (macOS's own is 3.9) |
| log rotation and `<job>.env` | `ExecStartPre=... rotate`, `EnvironmentFile=` | `agent-daemons.py exec --log <log> --env-file <home>/config/<job>.env -- <python> -u <script>` |
| restart on exit but 0 | `Restart=always`, `RestartPreventExitStatus=0` | `KeepAlive` `SuccessfulExit=false` |
| crash spacing | 10 s backing off to 5 min (`RestartSteps`) | a fixed 10 s (`ThrottleInterval`); launchd has no back-off |
| refresh log | the journal | `~/.local/state/agent-fleet/daemons-refresh.log` |

- **No template units.** Each agent's job plists are rendered by `--install
  <agent>` straight into `~/Library/LaunchAgents` and bootstrapped there.
  `render-units --units refresh` renders the refresh plist; `--units all` adds a
  re-render of every job plist already installed, which is how `fleet install`
  carries a template change to every agent.
- **`exec` is the job's first process.** It rotates the log, points stdout and
  stderr at it (launchd opened them on the path before the rotation), applies
  `<job>.env` over the environment the plist set, and `execve`s the daemon, so
  the pid launchd watches and the argv a reader sees are the daemon's. Like
  `rotate` it reads no host settings and imports nothing from the fleet.
- **The environment is in the plist, and a process's environment cannot be read.**
  macOS gives another process's argv but not its environment, so an agent
  verifies a daemon's `CLAUDE_CONFIG_DIR` and config from the job's definition,
  `launchctl print gui/<uid>/<label>`, not from the process. `refresh` does the
  same: the script comes from the process's argv, the config from the
  definition, and `--dry-run` says `(config from job definition)`.
- **A replaced log is read with `lsof`.** launchd opens `StandardOutPath` at
  each spawn and the `exec` shim reopens the log, so a log rewritten in place
  leaves the daemon writing to the old inode exactly as on Linux. macOS has no
  `/proc`, so refresh and `status` read the job's stdout and stderr with
  `/usr/sbin/lsof -a -p <pid> -d 1,2 +L -F ftikn` (inode and link count; it
  ships with macOS and reads the user's own processes) and restart the job the
  same way. **A deleted log cannot be salvaged there**: macOS has no `/proc`
  and no unprivileged way to read a file another process holds once its last
  name is gone (lsof names the descriptor; nothing reads it). A moved log is
  read by the name lsof reports, its inode checked. For a deleted one the
  `DAEMON-REFRESH` line ends `salvage: none, the replaced file is deleted, and
  without /proc (macOS) nothing can read it`, and the daemon's lines since the
  replacement are lost at the restart.
- **Every plist names the install's host settings.** launchd starts a job
  with the user's real HOME, so each job and the refresh job carry
  `FLEET_HOST_CONFIG`, the host.json `fleet install` writes (`render-units
  --host-config`). `refresh` reads the host settings before anything else and
  exits 3 with one line naming the file when there are none, where it would
  otherwise find no job and exit 0 having refreshed nothing.
- **A restart is `bootout` then `bootstrap`**, which re-reads the plist.
  `launchctl kickstart -k` restarts the process from the definition already
  loaded, so a changed plist would never take effect.
- `--uninstall <agent>` boots that agent's jobs out and removes their plists;
  with no agent it also boots out and removes the refresh job.

Look:

```bash
launchctl print gui/$(id -u)/<prefix>.sched.<agent>     # state, pid, runs, environment, last exit code
python3 <fleet>/systemd/agent-daemons.py status <agent>
tail -n 50 <agents-root>/<agent>/state/daemons/sched.log
tail -n 20 ~/.local/state/agent-fleet/daemons-refresh.log
```

`runs` counts every spawn, a manual `launchctl kickstart` included, so `runs - 1`
is the restart count `status` reports. The follower does not count the start
that brings back a job its last check saw stopped (the kickstart its GUARD
alert names, or a person's): that is recovery, `DAEMON-OK`, not a restart of
its own.

## Exit codes

`0` ran (or refused as a duplicate follower); `2` usage error or refused,
nothing changed; `3` environment fault: no host settings, no `lib/fleetlib`
beside the script, a broken transport descriptor, or nothing to render the
units against.
