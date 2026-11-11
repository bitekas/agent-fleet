# Conventions and house rules

An install tells the fleet how it works through two parts of its install manifest, `<install root>/.claude/fleet.json` (template: `templates/fleet.example.json`): the **conventions slot** and the **house rules**. Agents read both through `fleet settings`; Python code reads them with `fleetlib.manifest.settings(fleetlib.manifest.load(fleetlib.paths.install_root()))`.

## Conventions slot

**The fleet ships no development convention.** Where a fleet skill needs one, it names a convention key and reads the install's value with `fleet settings conventions.<key>`. The vocabulary is fixed by the fleet:

| Key | What it answers | Read by |
|---|---|---|
| `definition_of_done` | the check a task passes before it is reported complete | the `agent` skill, section 4; persona templates |
| `feature_checklist` | where a feature's working checklist lives, re-read after a compaction | the `agent` skill, section 4 |
| `branch_naming` | how branches and commit subjects are named | the `agent` skill, section 4; persona templates |
| `workspace` | where and how a write to a repository happens | persona templates |
| `release` | how a release is cut and shipped | persona templates |
| `environments` | which environments exist and what deploys where | persona templates |
| `people_notes` | where the install records standing requests from people, such as how a person wants to receive questions | the `talking-to-humans` skill, rules 1, 4 and 5 |

A value is one of:

- `{"skill": "<name>"}` - load that skill, the install's own `.claude/skills/<name>/SKILL.md`;
- `{"doc": "<repo-relative path>"}` - read that file; `<placeholders>` such as `<feature-slug>` are allowed inside the path, filled in when it is read (a value that is one `<...>` as a whole with a space inside, such as `<Your Name>`, is the template's placeholder, and the manifest is refused naming its key); `fleet settings` refuses a skill or a doc path, placeholders aside, that names no file in the install;
- either of the two with an optional `"section": "<heading or number>"` - read only that part;
- `null`.

**Absent or `null` means the install has no such convention.** The reading skill skips that step and says it skipped it. It never substitutes a default process.

## House rules

Each rule has a fleet default, applied when the manifest leaves the key out. A manifest that sets part of an object keeps the defaults of the rest (setting only `blocker_chase.tz` keeps the default days and hours); a list (`days`, `cities`) replaces the default list.

| Key | Default | Rule |
|---|---|---|
| `house_rules.questions_per_message` | `1` | the most questions an agent puts to a person in one message; the rule itself is in the `talking-to-humans` skill |
| `house_rules.blocker_chase.every_minutes` | `60` | how often an agent re-asks a person about an open blocker |
| `house_rules.blocker_chase.tz` | `"UTC"` | the time zone of the chase window |
| `house_rules.blocker_chase.days` | `["mon","tue","wed","thu","fri"]` | the days the chase window is open |
| `house_rules.blocker_chase.start` | `"09:00"` | the window opens (24-hour `HH:MM`) |
| `house_rules.blocker_chase.end` | `"18:00"` | the window closes (24-hour `HH:MM`) |
| `house_rules.state_the_fact` | `true` | write what is true now, not how it came to be; its home is the `agent` skill, section 7 |
| `house_rules.times.cities` | `[{"name": "UTC", "tz": "UTC"}]` | the clocks a reported time is rendered in, in this order; each entry is a `name` the reader sees and an IANA `tz` |
| `house_rules.ascii_skill_prose` | `true` | skill prose is plain ASCII; the rule itself is in the `claude-skill` skill, section 7 |

The `agent` skill's section 7 states each rule once with its key.

**Checked when the manifest loads**, each refused with the offending key named:

- `every_minutes` divides 1440 (a day in minutes);
- `blocker_chase.tz` and every city's `tz` load as IANA time zones on the host;
- `days` is a non-empty subset of `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`, each at most once;
- `start` is before `end`;
- `questions_per_message` is a positive integer; `state_the_fact` and `ascii_skill_prose` are `true` or `false`.

## Contributing to the fleet

An install whose agents commit to the fleet repository declares `upstream` in its manifest; one whose agents do not leaves it out. Where any install on a host declares it, or the checkout owner's identities file names anyone, `fleet upgrade` refuses a commit not made by a trusted identity as outside work; anywhere else it skips that check and trusts the release tag (`SETUP.md` section 9).

## Adopted projects

A project takes the fleet with `fleet adopt <project>`, which writes its install manifest from the template when it has none and merges one SessionStart hook, the **session check**, into its `.claude/settings.json`. Every adopted project carries the session check, committed with the manifest.

Every session started in the project runs it. It is silent while the fleet is present: the host settings name a fleet checkout, that checkout is at or above `fleet.min_tag`, and every skill in `skills` is linked for the session's config directory (`$CLAUDE_CONFIG_DIR`, else `~/.claude`). Otherwise it puts one notice into the session that names the cause and its remedy: an install request and the shell commands when the fleet is missing, `fleet upgrade <min_tag>` when it is older, `fleet link` when skills are not linked. An agent reports the notice to the person who runs the host and does not install, upgrade or link the fleet itself.

The hook needs no fleet to speak: on a host without a checkout it prints the missing-fleet notice from plain `sh`. It never stops a session. `fleet status` reports an install whose `.claude/settings.json` lacks it as drift, naming `fleet adopt <install root>`.
