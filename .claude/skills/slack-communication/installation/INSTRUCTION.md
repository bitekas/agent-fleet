# Installing `slack-communication`

Seven steps. When they are done, `installation/check` exits `0`.

**Install-wide and per agent.** Each agent that talks on Slack has its own Slack
app, its own bot token in its personal-secrets directory, and its own watcher
config at `<agents-root>/<agent>/config/slack-watch.json`, the path its watcher
unit reads; `/adding-an-agent` section 4 drives steps 1 to 3 for each agent it
adds. Step 3's `config.json` in the install context, step 4's claims directory,
step 5's `CONTEXT.md` and step 7's record are install-wide, once.

**Dependencies: none.** `watch.py` is Python 3 standard library only, which is
why there is no `requirements.txt` beside this file. If `python3` runs, the
skill runs. The claim it relies on is `/chat-transport`'s, which needs the
fleet installed on the host (`fleet install`).

**Two directories are named below.** `${CLAUDE_SKILL_DIR}` is this skill's
directory in the fleet tree - the Skill tool substitutes it in `SKILL.md`; in a
shell, set it to that directory first. **The install context** is where this
install's own files for the skill live (`CONTEXT.md`, `config.json`,
`installation/.install-state.json`); `fleet where slack-communication` prints
it. Nothing an install writes goes in the skill directory.

---

## 1. Create the Slack app and install it to the workspace

`SKILL.md`, "Setting up a workspace", is the authority on which scopes are
needed and why `channels:join` is deliberately optional. Follow it, then come
back here.

Read the granted scopes off the live API rather than off any document:

```bash
curl -sS -D- -o /dev/null https://slack.com/api/auth.test \
  -H "Authorization: Bearer $TOKEN"    # x-oauth-scopes response header
```

## 2. Put your personal Slack key on disk

The key goes in a file of its own, never in a config file and never in a
document:

```bash
install -m 600 /dev/null <key path>
printf '%s' '<the bot token>' > <key path>
```

**It is a personal key.** It belongs to the agent that owns this surface, is
not shared with other agents, and is never pasted into any file in this skill -
step 3 records its PATH and nothing more. Its place is that agent's
personal-secrets directory (`/agent` section 3) -
`<agents-root>/<agent>/secrets/personal/slack-bot.key` in the default layout -
never the organization secrets directory, and it must be readable by the user
the watcher runs as. **Keep it outside any checkout**: a path inside one is a different file in every worktree, so the key
is missing from all but one of them, and one stray `git add` publishes it.

## 3. Create `config.json` in the install context

```bash
install -m 644 "${CLAUDE_SKILL_DIR}/config.example.json" "$(fleet where slack-communication)/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode. Then replace **every** placeholder. The `_comment` keys in the file say
what each value is and how to obtain it; they are stripped by the loader, so you
may keep or delete them. A watcher service reads the config its unit names in
`SLACK_WATCH_CONFIG`, `<agents-root>/<agent>/config/slack-watch.json` - each
agent's own copy, made the same way with `install -m 600`.

**A `config.json` whose key names do not match `config.example.json` fails
LOUDLY, naming the key that could not be resolved.** That is why a key-name
change does not move `SKILL.md`'s `version`: `version` exists to catch the state
where everything still runs and the behaviour is silently the old one, and an
unresolvable key name is never that state - it stops before anything runs.
Measured: `WATCH-CONFIG <file>: missing required key
'token.path'`, and `installation/check` reports that same line as
`NOT INSTALLED`, because it loads the watcher rather than re-implementing it.

The ones that are easy to get wrong:

- **`workspace.team_id`** is enforced at startup against the token's own team.
  Wrong value, refusal to poll. That is deliberate: the alternative is a watcher
  quietly serving a different workspace.
- **`state.prefix`** is live on-disk state, not a name. A second workspace on
  the same machine MUST get a different one, or the two watchers share cursors
  and a lock.
- **`known_users`** is display labels only, and it grants nothing. Give every
  bot the agent corresponds with a label too, so its lines read as a name rather
  than a bare id.

**There is no sender filter to configure, and that is the whole delivery
model**: every message is delivered except the bot's own and anything carrying a
subtype. So **channel membership is the only control over what reaches the
session** - a bot in a channel a machine feed writes to (a product feed, a CI
notifier) receives that feed message for message and wakes on each one. Keep the
bot out of such channels.

## 4. The claims directory (once per host)

The claim (`/chat-transport`, *Claiming a request*) decides which one agent acts
on a request by creating a claim file in ONE directory every agent on the host
shares - `claims_dir` in the host settings file `fleet install` wrote
(`~/.config/agent-fleet/host.json`). `fleet install` creates that directory,
mode 700, as the user every agent runs as, and nothing else creates it: a
mis-pointed path that resolved silently into a fresh directory would put two
agents in two claim spaces, where both win the same request. There is nothing
to do here beyond the check.

Mode 700, owned by that user, and a real directory rather than a symlink -
`installation/check` refuses anything else and says why.

A host without the directory fails LOUDLY - `claim.py` exits 3 and
`installation/check` exits 2, each naming the `fleet install` that creates it -
so, like a key-name change (step 3), it is outside what `SKILL.md`'s `version`
tracks.

## 5. Write `CONTEXT.md` in the install context

`config.json` is what the script reads; `CONTEXT.md` is what the agent reads.
Nothing enforces it, which is exactly why it has to be written by hand: a wrong
value here fails silently as bad judgement rather than loudly as an error.

It has to answer, at minimum: which workspace and bot, which channels exist and
what each is for, who the people are and which of them are authorized (and by
what basis), which agent owns the surface and under which config dir, and where
the policy charter lives.

## 6. Verify, offline then online

```bash
python3 "${CLAUDE_SKILL_DIR}/watch.test.py"                     # offline regression guard - must print ALL CHECKS PASSED
python3 "${CLAUDE_SKILL_DIR}/../chat-transport/claim.test.py"   # the claim's guard, incl. its race controls - must print ALL CHECKS PASSED
SLACK_WATCH_CONFIG=<config> python3 "${CLAUDE_SKILL_DIR}/watch.py" --once   # one poll + one full sweep against the real workspace
```

`--once` failing with `WATCH-CONFIG` names the key or the mismatch. `--once`
printing nothing is success: it means no new deliverable messages since the
cursors were baselined. It writes the cursor files of the config it runs under,
so run against a live watcher's config it consumes what it prints. It is
therefore not evidence that the watcher is reaching the right channels - an
empty watched set and a quiet workspace look identical here.

## 7. Record the install

`check` compares this file against the `version` in `SKILL.md`. Without it, the
install cannot be told from a stale one, so `check` reports stale.

It is a **specific** file and is committed like any other, so it reaches
machines that never ran this procedure. It therefore records the host it was
written on, and `check` reports stale anywhere else - run this step once per
machine. Its shape is one flat record,
`{"version", "installed_at", "host", "by"}`, with the version read from
`SKILL.md`:

```bash
python3 - "${CLAUDE_SKILL_DIR}/SKILL.md" "$(fleet where slack-communication)/installation" <<'PY'
import json, re, socket, sys, time, pathlib
here = pathlib.Path(sys.argv[2])
here.mkdir(parents=True, exist_ok=True)
v = int(re.search(r"^version:\s*(\d+)$", pathlib.Path(sys.argv[1]).read_text(), re.M).group(1))
(here / ".install-state.json").write_text(json.dumps(
    {"version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "host": socket.gethostname(), "by": "INSTRUCTION.md"}, indent=2) + "\n")
print("recorded version", v)
PY

"${CLAUDE_SKILL_DIR}/installation/check"   # expect: OK: installed and current (version N), ...
```

---

## After installing

**Arming the watcher is not part of the install.** It is a standing duty of the
agent that owns the surface, and only that agent's `CLAUDE_CONFIG_DIR` is
allowed to run it - any other exits `WATCH-GUARD` by design. The owner guard and
the single-instance lock are the daemon form's: `--once` checks neither, so the
step 6 smoke test runs under any `CLAUDE_CONFIG_DIR` and moves the cursors of
whatever config it is given. `SKILL.md` covers
running it as a service and arming its follower under a persistent Monitor;
`CONTEXT.md` names the units, the follower command and the owning agent.

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than the recorded
one. Re-read this file from the top: a bump means something here changed, and
the only way to know what is to walk it. Then redo step 7.

**A record below version 3** belongs to an install whose config may carry a
sender-allowlist key. The watcher has no sender filter: it delivers every message
except the bot's own and anything carrying a subtype, and it ignores such a key
without failing. Delete the key, and re-read the membership of every channel this
bot is in before arming it, because every bot in those channels reaches the
session.

**The bump buys "re-read this file", and nothing more.** `installation/check`
validates the install's `config.json` with `SLACK_WATCH_CONFIG` set to it - so
the per-agent configs the live watchers actually run from are not read by it at
all, and a green from it says nothing about them. The only thing that validates
a live config is starting the watcher against it.
