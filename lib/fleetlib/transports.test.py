"""Tests for fleetlib.transports: the registry over tests/fixtures/transports, the
three ways to choose the registry directory, and the descriptor loader refusing
every kind of bad descriptor with the file and key named."""

import copy
import json
import os
import re
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import DescriptorError, Refused, transports  # noqa: E402
from fleetlib._testkit import (FIXTURE_TRANSPORTS, REPO, IsolatedTest, read_json,  # noqa: E402
                               run_python, write_json)

# design 6.3, written out here: the fixture must carry exactly these values so a
# test written against it stays valid when the real slack descriptor lands.
DESIGN_SLACK = {
    "schema": 1,
    "name": "slack",
    "status": "working",
    "line_prefix": "SLACK",
    "kinds": ["channel", "dm", "thread"],
    "ids": {"user": "^U[A-Z0-9]{6,}$",
            "conversation": "^[CDG][A-Z0-9]{2,20}$",
            "message": "^[0-9]{9,10}\\.[0-9]{6}$"},
    "watch": {"script": "watch.py", "job": "slack-watch", "config_env": "SLACK_WATCH_CONFIG",
              "follow_include": "^SLACK |^DAEMON-|WATCH-GUARD|WATCH-INFO|Traceback|"
                                "WATCH-ERROR (discovery|dm-discovery)|WATCH-ERROR (?!.*429)"},
}
DESIGN_DISCORD = {
    "schema": 1,
    "name": "discord",
    "status": "placeholder",
    "line_prefix": "DISCORD",
    "kinds": ["channel", "dm", "thread"],
    "ids": {"user": "^[0-9]{17,20}$", "conversation": "^[0-9]{17,20}$", "message": "^[0-9]{17,20}$"},
    "watch": {"script": "watch.py", "job": "discord-watch", "config_env": "DISCORD_WATCH_CONFIG",
              "follow_include": "^DISCORD |^DAEMON-|WATCH-GUARD|WATCH-INFO|Traceback|WATCH-ERROR"},
}
DERIVED = ("skill", "skill_dir")


def bare(d):
    return {k: v for k, v in d.items() if k not in DERIVED}


class FixtureRegistryTest(IsolatedTest):
    def test_all_working_get(self):
        names = [d["name"] for d in transports.all(FIXTURE_TRANSPORTS)]
        self.assertEqual(names, ["discord", "slack"])
        self.assertEqual([d["name"] for d in transports.working(FIXTURE_TRANSPORTS)], ["slack"])
        self.assertEqual(bare(transports.get("slack", FIXTURE_TRANSPORTS)), DESIGN_SLACK)
        self.assertEqual(bare(transports.get("discord", FIXTURE_TRANSPORTS)), DESIGN_DISCORD)

    def test_derived_skill_keys(self):
        d = transports.get("slack", FIXTURE_TRANSPORTS)
        self.assertEqual(d["skill"], "slack-communication")
        self.assertEqual(d["skill_dir"], str(FIXTURE_TRANSPORTS / "slack-communication"))

    def test_unknown_name_is_refused(self):
        err = self.assertFleetError(Refused, transports.get, "irc", FIXTURE_TRANSPORTS, exit_code=2)
        self.assertIn("discord, slack", str(err))

    def test_slack_ids_accept_and_reject(self):
        ids = transports.get("slack", FIXTURE_TRANSPORTS)["ids"]
        self.assertRegex("CEXAMPLE01", ids["conversation"])
        self.assertRegex("1700000000.000001", ids["message"])
        self.assertIsNone(re.search(ids["message"], "x1700000000.000001"))


class RegistryDirTest(IsolatedTest):
    def test_default_is_the_fleet_tree_this_library_came_from(self):
        self.assertEqual(transports.registry_dir(), REPO / ".claude" / "skills")

    def test_environment_variable_overrides_the_default(self):
        os.environ["FLEET_TRANSPORTS_DIR"] = str(FIXTURE_TRANSPORTS)
        self.assertEqual(transports.registry_dir(), FIXTURE_TRANSPORTS)
        self.assertEqual([d["name"] for d in transports.working()], ["slack"])

    def test_argument_overrides_the_environment_variable(self):
        os.environ["FLEET_TRANSPORTS_DIR"] = str(self.tmp / "nowhere")
        self.assertEqual(transports.registry_dir(FIXTURE_TRANSPORTS), FIXTURE_TRANSPORTS)
        self.assertEqual(transports.all(self.tmp / "empty"), [])

    def test_environment_variable_reaches_a_child_process(self):
        env = {**os.environ, "FLEET_TRANSPORTS_DIR": str(FIXTURE_TRANSPORTS)}
        r = run_python("import sys; sys.path.insert(0, sys.argv[1]); from fleetlib import transports; "
                       "print(','.join(d['name'] for d in transports.working()))", REPO / "lib", env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "slack"), r.stderr)

    def test_real_slack_descriptor_equals_the_fixture_once_it_exists(self):
        real = REPO / ".claude" / "skills" / "slack-communication" / "transport.json"
        if not real.exists():
            self.skipTest(f"{real} does not exist yet; the fixture stands in for it")
        self.assertEqual(read_json(real), read_json(FIXTURE_TRANSPORTS / "slack-communication" / "transport.json"))


# (what is broken, mutation of a copy of DESIGN_SLACK, the key the refusal must name)
BAD = [
    ("schema 2", lambda d: d.update(schema=2), "schema"),
    ("schema bool", lambda d: d.update(schema=True), "schema"),
    ("name missing", lambda d: d.pop("name"), "name"),
    ("unknown key", lambda d: d.update(extra=1), "extra"),
    ("name uppercase", lambda d: d.update(name="Slack"), "name"),
    ("watch.job the session's", lambda d: d["watch"].update(job="session"), "watch.job"),
    ("watch.job the stall watchdog's", lambda d: d["watch"].update(job="stall-watchdog"), "watch.job"),
    ("status unknown", lambda d: d.update(status="beta"), "status"),
    ("line_prefix lowercase", lambda d: d.update(line_prefix="slack"), "line_prefix"),
    ("kinds empty", lambda d: d.update(kinds=[]), "kinds"),
    ("kinds unknown", lambda d: d.update(kinds=["channel", "group"]), "kinds"),
    ("kinds repeated", lambda d: d.update(kinds=["dm", "dm"]), "kinds"),
    ("ids not an object", lambda d: d.update(ids="x"), "ids"),
    ("ids.message missing", lambda d: d["ids"].pop("message"), "ids.message"),
    ("ids unknown key", lambda d: d["ids"].update(team="^T$"), "ids.team"),
    ("ids.user does not compile", lambda d: d["ids"].update(user="^U[$"), "ids.user"),
    ("ids.conversation unanchored", lambda d: d["ids"].update(conversation="[CDG][A-Z0-9]+"), "ids.conversation"),
    ("watch missing", lambda d: d.pop("watch"), "watch"),
    ("watch.follow_include missing", lambda d: d["watch"].pop("follow_include"), "watch.follow_include"),
    ("watch.follow_include does not compile", lambda d: d["watch"].update(follow_include="("),
     "watch.follow_include"),
    ("watch.script a path", lambda d: d["watch"].update(script="bin/watch.py"), "watch.script"),
    ("watch.job not a name", lambda d: d["watch"].update(job="Slack Watch"), "watch.job"),
    ("watch.config_env not a variable", lambda d: d["watch"].update(config_env="1BAD"), "watch.config_env"),
]


class LoaderTest(IsolatedTest):
    def registry(self, descriptors, name="skills"):
        """A skills dir holding one <skill>/transport.json per (skill, content) pair."""
        base = self.tmp / name
        for skill, content in descriptors:
            path = base / skill / "transport.json"
            if isinstance(content, str):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            else:
                write_json(path, content)
        return base

    def test_bad_base_is_valid(self):
        # The control for BAD: the unbroken copy loads, so each refusal below is
        # caused by its own mutation.
        self.assertEqual([bare(d) for d in transports.all(self.registry([("x-communication", DESIGN_SLACK)]))],
                         [DESIGN_SLACK])

    def test_every_bad_descriptor_is_refused_naming_file_and_key(self):
        for i, (what, mutate, key) in enumerate(BAD):
            with self.subTest(what):
                d = copy.deepcopy(DESIGN_SLACK)
                mutate(d)
                base = self.registry([("x-communication", d)], name=f"case{i}")
                err = self.assertFleetError(DescriptorError, transports.all, base, exit_code=3, key=key)
                self.assertIn("x-communication/transport.json", str(err))

    def test_invalid_json_is_refused(self):
        base = self.registry([("x-communication", "{ not json")])
        err = self.assertFleetError(DescriptorError, transports.all, base, exit_code=3)
        self.assertIn("x-communication", str(err))

    def test_duplicate_name_is_refused(self):
        base = self.registry([("a-communication", DESIGN_SLACK), ("b-communication", DESIGN_SLACK)])
        err = self.assertFleetError(DescriptorError, transports.all, base, exit_code=3, key="name")
        self.assertIn("a-communication", str(err))
        self.assertIn("b-communication", str(err))

    def test_one_bad_descriptor_refuses_the_whole_registry(self):
        broken = copy.deepcopy(DESIGN_DISCORD)
        broken["status"] = "beta"
        base = self.registry([("slack-communication", DESIGN_SLACK), ("discord-communication", broken)])
        self.assertFleetError(DescriptorError, transports.working, base, exit_code=3, key="status")

    def test_fixture_files_are_the_design_values_byte_for_value(self):
        for skill, want in (("slack-communication", DESIGN_SLACK), ("discord-communication", DESIGN_DISCORD)):
            got = json.loads((FIXTURE_TRANSPORTS / skill / "transport.json").read_text(encoding="utf-8"))
            self.assertEqual(got, want, skill)


if __name__ == "__main__":
    unittest.main()
