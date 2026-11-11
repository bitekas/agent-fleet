# golden-v1.0.3 - the Linux units every later tree must render

These four files are `agent-daemons.py render-units --units all` of the
**v1.0.3 tag** (its own `systemd/` and `lib/`, from `git archive v1.0.3`), never
of a later tree: a fixture rendered from the tree under test agrees with any
change to that tree, so it could not see the change.

They pin what the hosts running the fleet already run. Every Linux agent's
daemons run from units of this exact shape; a render that differs changes, at
the next `fleet install --units all`, what every one of them runs. Adding the
macOS backend changed `agent-daemons.py` throughout, and this is the check that
the Linux half came out byte for byte the same.

How they were made, and how `golden_render()` in `systemd/agent-daemons.test.py`
renders the tree under test for comparison:

- the fleet tree at `<fleet>`, with the descriptors of
  `tests/fixtures/systemd/transports/` copied to
  `<fleet>/.claude/skills/<name>/transport.json` and `FLEET_TRANSPORTS_DIR`
  pointing there (a working Slack transport, a placeholder Discord one);
- host settings with `agents_root` `<agents-root>`, one agent home `ada` whose
  install checkout is `product`;
- the systemd backend, no `FLEET_PYTHON`;
- then the tree path replaced by `<fleet>`, the agents root by `<agents-root>`,
  and the tag in each rendered-by header by `<tag>`. Nothing else is changed.

A deliberate change to the Linux units is written in UNIT_DELTAS in that test
(lines inserted after an anchor line, each anchor required exactly once), so the
comparison names every difference from what the hosts run. Today's deltas, in
the scheduler, watcher and refresh units: `Environment=PYTHONDONTWRITEBYTECODE=1`
with its comment line (no bytecode is written into a checkout the agents user
may not change), and after it `Environment=FLEET_HOST_CONFIG=<host-config>` with
its two comment lines (each unit reads the host settings file it names;
the test puts that render's path in place of `<host-config>`).

Regenerate the files only from a release tag that ships those deltas, never
from a working tree, and empty UNIT_DELTAS in the same commit; say which tag in
this file's title and in the test's check.
