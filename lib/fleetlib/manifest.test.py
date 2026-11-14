"""Tests for fleetlib.manifest: schema-1 validation (every invariant refused with
the offending key named), comment stripping, settings() defaults, and the two
documents that restate the schema (templates/fleet.example.json, CONVENTIONS.md)."""

import copy
import json
import os
import re
import shutil
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import DescriptorError, EnvironmentFault, ManifestError, manifest  # noqa: E402
from fleetlib._testkit import (FIXTURE_INSTALL, FIXTURE_TRANSPORTS, MINIMAL, REPO,  # noqa: E402
                               IsolatedTest, make_install, read_json, write_json)


def fixture():
    return manifest.strip_comments(read_json(FIXTURE_INSTALL / ".claude" / "fleet.json"))


# The fixture install's skills, read from it: the refusals below mutate this list.
FLEET_SKILLS = fixture()["skills"]

# design 6.1's defaults, written out here and not derived from manifest.py, so a
# changed default reds this test instead of agreeing with itself.
DESIGN_HOUSE_RULES = {
    "questions_per_message": 1,
    "blocker_chase": {"every_minutes": 60, "tz": "UTC",
                      "days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "18:00"},
    "state_the_fact": True,
    "times": {"cities": [{"name": "UTC", "tz": "UTC"}]},
    "ascii_skill_prose": True,
}
DESIGN_SECRETS = {"legacy_env": None, "default_dir": "~/.fleet-secrets"}


def setp(d, dotted, value):
    """Set (or, with value DEL, delete) a dotted key such as house_rules.times.cities.1.tz."""
    *parts, last = dotted.split(".")
    for p in parts:
        d = d[int(p)] if isinstance(d, list) else d[p]
    if value is DEL:
        del d[last]
    elif isinstance(d, list):
        d[int(last)] = value
    else:
        d[last] = value


DEL = object()

# (what is broken, [(dotted key to set, value)...], the key the refusal must name)
REFUSALS = [
    ("unknown top-level key", [("extra", 1)], "extra"),
    ("schema missing", [("schema", DEL)], "schema"),
    ("fleet missing", [("fleet", DEL)], "fleet"),
    ("skills missing", [("skills", DEL)], "skills"),
    ("transports missing", [("transports", DEL)], "transports"),
    ("schema 2", [("schema", 2)], "schema"),
    ("schema as a string", [("schema", "1")], "schema"),
    ("schema as a bool", [("schema", True)], "schema"),
    ("schema as a float", [("schema", 1.0)], "schema"),
    ("fleet not an object", [("fleet", "x")], "fleet"),
    ("fleet.repo missing", [("fleet.repo", DEL)], "fleet.repo"),
    ("fleet.min_tag not a tag", [("fleet.min_tag", "1.0")], "fleet.min_tag"),
    ("unknown fleet key", [("fleet.branch", "main")], "fleet.branch"),
    ("skills a string", [("skills", "agent")], "skills"),
    ("skills empty", [("skills", [])], "skills"),
    ("skills duplicate", [("skills", FLEET_SKILLS + ["agent"])], "skills"),
    ("skills bad name", [("skills", FLEET_SKILLS + ["Bad Name"])], "skills"),
    ("transports.enabled empty", [("transports.enabled", [])], "transports.enabled"),
    ("transports.default missing", [("transports.default", DEL)], "transports.default"),
    ("unknown transports key", [("transports.fallback", "slack")], "transports.fallback"),
    # 6.1 invariant: transports.default is in transports.enabled
    ("default not enabled", [("transports.default", "discord")], "transports.default"),
    # 6.1 invariant: every enabled transport is a working transport in the fleet tree
    ("placeholder enabled", [("transports.enabled", ["slack", "discord"]),
                             ("skills", FLEET_SKILLS + ["discord-communication"])], "transports.enabled"),
    ("unknown transport enabled", [("transports.enabled", ["slack", "irc"])], "transports.enabled"),
    # 6.1 invariant: skills contains chat-transport and each enabled transport's skill
    ("skills lack chat-transport", [("skills", [s for s in FLEET_SKILLS if s != "chat-transport"])], "skills"),
    ("skills lack the slack skill", [("skills", [s for s in FLEET_SKILLS if s != "slack-communication"])], "skills"),
    ("unknown convention", [("conventions.dod", None)], "conventions.dod"),
    ("convention a string", [("conventions.release", "release")], "conventions.release"),
    ("convention with two forms", [("conventions.release", {"skill": "a", "doc": "b"})], "conventions.release"),
    ("convention with no form", [("conventions.release", {"section": "2"})], "conventions.release"),
    ("convention empty skill", [("conventions.release", {"skill": ""})], "conventions.release.skill"),
    ("convention bool section", [("conventions.release", {"skill": "a", "section": True})],
     "conventions.release.section"),
    ("convention unknown field", [("conventions.release", {"skill": "a", "anchor": "x"})],
     "conventions.release.anchor"),
    ("house_rules not an object", [("house_rules", [])], "house_rules"),
    ("unknown house rule", [("house_rules.questions_per_mesage", 1)], "house_rules.questions_per_mesage"),
    ("questions_per_message zero", [("house_rules.questions_per_message", 0)], "house_rules.questions_per_message"),
    ("questions_per_message a string", [("house_rules.questions_per_message", "1")],
     "house_rules.questions_per_message"),
    # 6.1 invariant: every_minutes divides 1440
    ("every_minutes 7", [("house_rules.blocker_chase.every_minutes", 7)], "house_rules.blocker_chase.every_minutes"),
    ("every_minutes 0", [("house_rules.blocker_chase.every_minutes", 0)], "house_rules.blocker_chase.every_minutes"),
    # 6.1 invariant: every IANA zone loads
    ("blocker tz unknown", [("house_rules.blocker_chase.tz", "Mars/Olympus_Mons")], "house_rules.blocker_chase.tz"),
    ("blocker tz path", [("house_rules.blocker_chase.tz", "../../etc/passwd")], "house_rules.blocker_chase.tz"),
    ("city tz unknown", [("house_rules.times.cities.1.tz", "Asia/Atlantis")], "house_rules.times.cities[1].tz"),
    # 6.1 invariant: days is a non-empty subset of mon..sun
    ("days empty", [("house_rules.blocker_chase.days", [])], "house_rules.blocker_chase.days"),
    ("days unknown", [("house_rules.blocker_chase.days", ["mon", "funday"])], "house_rules.blocker_chase.days"),
    ("days repeated", [("house_rules.blocker_chase.days", ["mon", "mon"])], "house_rules.blocker_chase.days"),
    # 6.1 invariant: start < end
    ("start equals end", [("house_rules.blocker_chase.start", "17:00")], "house_rules.blocker_chase.start"),
    ("start after end", [("house_rules.blocker_chase.start", "18:00")], "house_rules.blocker_chase.start"),
    ("start not HH:MM", [("house_rules.blocker_chase.start", "8:30")], "house_rules.blocker_chase.start"),
    ("end 24:00", [("house_rules.blocker_chase.end", "24:00")], "house_rules.blocker_chase.end"),
    ("unknown blocker key", [("house_rules.blocker_chase.weekends", False)], "house_rules.blocker_chase.weekends"),
    ("state_the_fact a string", [("house_rules.state_the_fact", "yes")], "house_rules.state_the_fact"),
    ("ascii_skill_prose an int", [("house_rules.ascii_skill_prose", 1)], "house_rules.ascii_skill_prose"),
    ("cities empty", [("house_rules.times.cities", [])], "house_rules.times.cities"),
    ("city without a name", [("house_rules.times.cities.0.name", DEL)], "house_rules.times.cities[0].name"),
    ("city unknown key", [("house_rules.times.cities.0.flag", "x")], "house_rules.times.cities[0].flag"),
    ("secrets.legacy_env not a name", [("secrets.legacy_env", "NOT A VAR")], "secrets.legacy_env"),
    ("secrets.default_dir empty", [("secrets.default_dir", "")], "secrets.default_dir"),
    ("unknown secrets key", [("secrets.path", "/x")], "secrets.path"),
    ("unknown upstream key", [("upstream.reviewers", [])], "upstream.reviewers"),
    ("identity without email", [("upstream.identity.email", DEL)], "upstream.identity.email"),
    ("deny_list a number", [("upstream.deny_list", 5)], "upstream.deny_list"),
    # A value that is one <...> as a whole with a space inside is the template's placeholder.
    ("placeholder repo", [("fleet.repo", "<clone URL>")], "fleet.repo"),
    ("placeholder identity", [("upstream.identity.name", "<Your Name>")], "upstream.identity.name"),
    ("placeholder convention skill", [("conventions.release", {"skill": "<your release skill>"})],
     "conventions.release.skill"),
    ("placeholder convention doc", [("conventions.release", {"doc": "<your process doc>"})],
     "conventions.release.doc"),
    ("placeholder in a list", [("house_rules.times.cities.0.name", "<city name>")],
     "house_rules.times.cities[0].name"),
]

# Bracketed values that are install data, not the template's placeholder form.
NOT_PLACEHOLDERS = [
    ("chat mention as reviewer", "upstream.outside_pr_reviewer", "<@ada>"),
    ("bracketed address", "upstream.identity.email", "<ada@example.com>"),
    ("one-word read-time placeholder as a section", "conventions.branch_naming.section", "<version>"),
]


class LoadTest(IsolatedTest):
    def load(self, m):
        return manifest.load(make_install(self.tmp / "inst", m), skills_dir=FIXTURE_TRANSPORTS)

    def test_refusal_base_is_valid(self):
        # The control for REFUSALS: the unbroken base loads, so each refusal below is
        # caused by its own mutation and not by a broken base.
        self.assertEqual(self.load(fixture()), fixture())

    def test_every_refusal_names_its_key(self):
        for what, edits, key in REFUSALS:
            with self.subTest(what):
                m = fixture()
                for dotted, value in edits:
                    setp(m, dotted, value)
                self.assertFleetError(ManifestError, self.load, m, exit_code=2, key=key)

    def test_minimal_manifest_loads(self):
        self.assertEqual(self.load(MINIMAL), MINIMAL)

    def test_a_placeholder_inside_a_doc_path_loads(self):
        # The read-time placeholder of a doc path (`<feature-slug>`) is install data;
        # only a value that is a placeholder AS A WHOLE is refused. The fixture's
        # feature_checklist carries one too, so test_refusal_base_is_valid covers it
        # as well; this pins it where the rule's two halves sit side by side.
        m = fixture()
        m["conventions"]["release"] = {"doc": "docs/releases/<version>.md", "section": "Cutting <version>"}
        self.assertEqual(self.load(m)["conventions"]["release"]["doc"], "docs/releases/<version>.md")

    def test_bracketed_install_values_load(self):
        for what, dotted, value in NOT_PLACEHOLDERS:
            with self.subTest(what):
                m = fixture()
                setp(m, dotted, value)
                self.assertEqual(self.load(m), m)

    def test_a_placeholder_in_a_typed_field_is_named_as_unfilled(self):
        # Checked before the typed checks: the tag regex would refuse the same key
        # as malformed, and only the message says the file was never filled in.
        m = fixture()
        m["fleet"]["min_tag"] = "<the oldest fleet release>"
        err = self.assertFleetError(ManifestError, self.load, m, exit_code=2, key="fleet.min_tag")
        self.assertIn("placeholder", str(err))

    def test_comments_are_stripped_at_every_depth(self):
        m = copy.deepcopy(MINIMAL)
        m["_comment"] = "top"
        m["fleet"]["_comment"] = ["nested"]
        m["house_rules"] = {"times": {"cities": [{"_comment": "in a list", "name": "Tokyo", "tz": "Asia/Tokyo"}]}}
        got = self.load(m)
        self.assertNotIn("_comment", got)
        self.assertNotIn("_comment", got["fleet"])
        self.assertEqual(got["house_rules"]["times"]["cities"], [{"name": "Tokyo", "tz": "Asia/Tokyo"}])

    def test_invalid_json_is_refused(self):
        (self.tmp / "inst" / ".claude").mkdir(parents=True)
        (self.tmp / "inst" / ".claude" / "fleet.json").write_text("{", encoding="utf-8")
        self.assertFleetError(ManifestError, manifest.load, self.tmp / "inst", exit_code=2)

    def test_missing_file_is_exit_3(self):
        self.assertFleetError(EnvironmentFault, manifest.load, self.tmp, exit_code=3, variable="FLEET_CONTEXT_ROOT")

    def test_a_bad_descriptor_in_the_registry_is_exit_3(self):
        bad = write_json(self.tmp / "skills" / "slack-communication" / "transport.json", {"schema": 1})
        with self.assertRaises(DescriptorError) as cm:
            manifest.load(make_install(self.tmp / "inst"), skills_dir=bad.parent.parent)
        self.assertEqual(cm.exception.exit_code, 3)

    def test_registry_from_environment_variable(self):
        os.environ["FLEET_TRANSPORTS_DIR"] = str(FIXTURE_TRANSPORTS)
        self.assertEqual(manifest.load(make_install(self.tmp / "inst")), MINIMAL)


class CheckPathsTest(IsolatedTest):
    """check_paths(): a convention or a deny list naming a file the install does not
    have is refused naming its key. The control is the same install with every file
    present, so each refusal is its missing file's."""

    FILES = {"conventions.definition_of_done.skill": ".claude/skills/example-dod/SKILL.md",
             "conventions.branch_naming.doc": "docs/process.md",
             "upstream.deny_list": ".claude/fleet/deny.txt"}

    def install(self, missing=None, **edits):
        m = copy.deepcopy(MINIMAL)
        m["conventions"] = {"definition_of_done": {"skill": "example-dod"},
                            "branch_naming": {"doc": "docs/process.md", "section": "Branch names"},
                            "feature_checklist": {"doc": "docs/checklists/<feature-slug>.md"},
                            "release": None}
        m["upstream"] = {"deny_list": ".claude/fleet/deny.txt"}
        for dotted, value in edits.items():
            setp(m, dotted.replace("__", "."), value)
        root = make_install(self.tmp / "inst", m)
        for key, rel in self.FILES.items():
            if key != missing:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("x\n", encoding="utf-8")
        return manifest.load(root, skills_dir=FIXTURE_TRANSPORTS), root

    def test_every_file_present_passes(self):
        m, root = self.install()
        self.assertIsNone(manifest.check_paths(m, root))
        self.assertFalse((root / "docs" / "checklists").exists(),
                         "the placeholder doc's directory exists, so this pass proves nothing about it")

    def test_each_missing_file_is_refused_naming_its_key(self):
        for key in self.FILES:
            with self.subTest(key):
                shutil.rmtree(self.tmp / "inst", ignore_errors=True)
                m, root = self.install(missing=key)
                self.assertFleetError(ManifestError, manifest.check_paths, m, root, exit_code=2, key=key)

    def test_a_skill_directory_without_skill_md_is_refused(self):
        m, root = self.install()
        (root / ".claude/skills/example-dod/SKILL.md").unlink()
        self.assertTrue((root / ".claude/skills/example-dod").is_dir())
        self.assertFleetError(ManifestError, manifest.check_paths, m, root, exit_code=2,
                              key="conventions.definition_of_done.skill")

    def test_null_or_absent_deny_list_and_an_absolute_doc_pass(self):
        doc = self.tmp / "elsewhere" / "process.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("x\n", encoding="utf-8")
        m, root = self.install(missing="upstream.deny_list", upstream__deny_list=None,
                               conventions__branch_naming__doc=str(doc))
        self.assertIsNone(manifest.check_paths(m, root))
        del m["upstream"]
        self.assertIsNone(manifest.check_paths(m, root))


class FleetSkillConventionTest(IsolatedTest):
    """check_paths(): a {"skill": X} convention names the install's own skill, or
    a fleet skill the manifest's `skills` lists and the fleet tree has. Each case
    runs against a fleet tree of its own (`skills_dir`), so the fleet skill's
    presence is the case's choice, never this repository's."""

    def setup(self, value, *, listed=(), own=(), fleet=()):
        m = copy.deepcopy(MINIMAL)
        m["skills"] = MINIMAL["skills"] + list(listed)
        m["conventions"] = {"release": value}
        root = make_install(self.tmp / "inst", m)
        for name in own:
            (root / ".claude/skills" / name).mkdir(parents=True)
            (root / ".claude/skills" / name / "SKILL.md").write_text("x\n", encoding="utf-8")
        skills_dir = self.tmp / "fleet" / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        for name in fleet:
            (skills_dir / name).mkdir()
            (skills_dir / name / "SKILL.md").write_text("x\n", encoding="utf-8")
        return manifest.load(root, skills_dir=FIXTURE_TRANSPORTS), root, skills_dir

    def test_the_install_own_skill_is_accepted(self):
        m, root, fleet = self.setup({"skill": "example-release"}, own=["example-release"])
        self.assertIsNone(manifest.check_paths(m, root, skills_dir=fleet))

    def test_a_fleet_skill_the_manifest_lists_is_accepted(self):
        m, root, fleet = self.setup({"skill": "release", "section": 3}, listed=["release"], fleet=["release"])
        self.assertFalse((root / ".claude/skills/release").exists(), "the install has its own copy")
        self.assertIsNone(manifest.check_paths(m, root, skills_dir=fleet))

    def test_a_fleet_skill_the_manifest_does_not_list_is_refused(self):
        # The install that declined the group but kept a convention pointing at it.
        m, root, fleet = self.setup({"skill": "release"}, fleet=["release"])
        err = self.assertFleetError(ManifestError, manifest.check_paths, m, root, skills_dir=fleet,
                                    exit_code=2, key="conventions.release.skill")
        self.assertIn("`skills` does not list it", str(err))

    def test_a_listed_skill_the_fleet_tree_lacks_is_refused(self):
        m, root, fleet = self.setup({"skill": "release"}, listed=["release"])
        err = self.assertFleetError(ManifestError, manifest.check_paths, m, root, skills_dir=fleet,
                                    exit_code=2, key="conventions.release.skill")
        self.assertIn("the fleet tree has no", str(err))

    def test_a_name_in_neither_is_refused(self):
        m, root, fleet = self.setup({"skill": "release"})
        err = self.assertFleetError(ManifestError, manifest.check_paths, m, root, skills_dir=fleet,
                                    exit_code=2, key="conventions.release.skill")
        self.assertIn("neither", str(err))

    def test_the_default_fleet_tree_is_the_one_this_library_is_in(self):
        # No skills_dir: the fleet tree is this repository, whose software-development
        # skill exists, so listing it is all an install needs to point a key at it.
        self.assertTrue((REPO / ".claude/skills/software-development/SKILL.md").is_file())
        m, root, _ = self.setup({"skill": "software-development"}, listed=["software-development"])
        self.assertIsNone(manifest.check_paths(m, root))
        m["skills"].remove("software-development")
        self.assertFleetError(ManifestError, manifest.check_paths, m, root, exit_code=2,
                              key="conventions.release.skill")


class OptionalConventionTest(IsolatedTest):
    """`conventions.people_notes` is optional, so a schema-1 manifest without it is
    still valid: it loads unchanged and reads the key as null (no such convention),
    and one that sets it resolves in every value form. The fixture's conventions
    object leaves the key out, so it is the case of an install that never set it."""

    def load(self, m):
        return manifest.load(make_install(self.tmp / "inst", m), skills_dir=FIXTURE_TRANSPORTS)

    def test_a_manifest_without_the_key_loads_and_reads_it_as_null(self):
        m = fixture()
        m["conventions"].pop("people_notes", None)
        loaded = self.load(m)
        self.assertEqual(loaded, m)
        self.assertIsNone(manifest.settings(loaded)["conventions"]["people_notes"])

    def test_the_key_resolves_in_every_value_form(self):
        for value in ({"doc": "docs/people-notes.md"}, {"skill": "example-people-notes"},
                      {"doc": "docs/team.md", "section": "Questions"}, None):
            with self.subTest(value=value):
                m = fixture()
                m["conventions"]["people_notes"] = value
                self.assertEqual(manifest.settings(self.load(m))["conventions"]["people_notes"], value)

    def test_check_paths_follows_the_key(self):
        m = copy.deepcopy(MINIMAL)
        m["conventions"] = {"people_notes": {"doc": "docs/people-notes.md"}}
        loaded = self.load(m)
        root = self.tmp / "inst"
        self.assertFleetError(ManifestError, manifest.check_paths, loaded, root, exit_code=2,
                              key="conventions.people_notes.doc")
        (root / "docs").mkdir()
        (root / "docs" / "people-notes.md").write_text("x\n", encoding="utf-8")
        self.assertIsNone(manifest.check_paths(loaded, root))


class FixtureTest(IsolatedTest):
    def test_fixture_install_loads(self):
        m = manifest.load(FIXTURE_INSTALL, skills_dir=FIXTURE_TRANSPORTS)
        self.assertEqual(m["skills"], read_json(FIXTURE_INSTALL / ".claude" / "fleet.json")["skills"])
        self.assertEqual(m["transports"], {"enabled": ["slack"], "default": "slack"})

    def test_fixture_house_rules_all_differ_from_the_defaults(self):
        # A test reading a house rule from the fixture can only tell the manifest's
        # value from a default if every leaf differs.
        hr = manifest.settings(manifest.load(FIXTURE_INSTALL, skills_dir=FIXTURE_TRANSPORTS))["house_rules"]
        for k in ("questions_per_message", "state_the_fact", "times", "ascii_skill_prose"):
            self.assertNotEqual(hr[k], DESIGN_HOUSE_RULES[k], k)
        for k in DESIGN_HOUSE_RULES["blocker_chase"]:
            self.assertNotEqual(hr["blocker_chase"][k], DESIGN_HOUSE_RULES["blocker_chase"][k], k)
        self.assertEqual([c["tz"] for c in hr["times"]["cities"]], ["Europe/Berlin", "Asia/Tokyo", "Asia/Kolkata"])

    def test_fixture_conventions_use_all_three_forms(self):
        conv = manifest.settings(manifest.load(FIXTURE_INSTALL, skills_dir=FIXTURE_TRANSPORTS))["conventions"]
        forms = {("skill" if v and "skill" in v else "doc" if v else None) for v in conv.values()}
        self.assertEqual(forms, {"skill", "doc", None})
        self.assertTrue(any(v and "doc" in v and "section" in v for v in conv.values()))


class SettingsTest(IsolatedTest):
    def test_defaults_equal_the_design(self):
        self.assertEqual(manifest.DEFAULT_HOUSE_RULES, DESIGN_HOUSE_RULES)
        self.assertEqual(manifest.DEFAULT_SECRETS, DESIGN_SECRETS)
        self.assertEqual(manifest.DEFAULT_CONVENTIONS, {k: None for k in manifest.CONVENTION_KEYS})

    def test_minimal_manifest_gets_every_default(self):
        s = manifest.settings(MINIMAL)
        self.assertEqual(s["house_rules"], DESIGN_HOUSE_RULES)
        self.assertEqual(s["secrets"], DESIGN_SECRETS)
        self.assertEqual(s["conventions"], {k: None for k in manifest.CONVENTION_KEYS})
        self.assertNotIn("upstream", s, "upstream has no defaults")
        self.assertEqual((s["schema"], s["fleet"], s["skills"], s["transports"]),
                         (1, MINIMAL["fleet"], MINIMAL["skills"], MINIMAL["transports"]))

    def test_partial_objects_merge_and_lists_replace(self):
        m = dict(MINIMAL, house_rules={"blocker_chase": {"tz": "Asia/Tokyo", "days": ["sat"]},
                                       "times": {"cities": [{"name": "Kolkata", "tz": "Asia/Kolkata"}]}},
                 secrets={"legacy_env": "EXAMPLE_SECRETS_DIR"},
                 conventions={"release": {"skill": "example-release"}})
        s = manifest.settings(m)
        self.assertEqual(s["house_rules"]["blocker_chase"],
                         {"every_minutes": 60, "tz": "Asia/Tokyo", "days": ["sat"], "start": "09:00", "end": "18:00"})
        self.assertEqual(s["house_rules"]["times"]["cities"], [{"name": "Kolkata", "tz": "Asia/Kolkata"}])
        self.assertEqual(s["house_rules"]["questions_per_message"], 1)
        self.assertEqual(s["secrets"], {"legacy_env": "EXAMPLE_SECRETS_DIR", "default_dir": "~/.fleet-secrets"})
        self.assertEqual(s["conventions"]["release"], {"skill": "example-release"})
        self.assertIsNone(s["conventions"]["definition_of_done"])

    def test_partial_merge_is_validated_as_merged(self):
        # start 19:00 alone is valid HH:MM, but against the default end 18:00 it breaks start < end.
        m = dict(MINIMAL, house_rules={"blocker_chase": {"start": "19:00"}})
        make_install(self.tmp / "inst", m)
        self.assertFleetError(ManifestError, manifest.load, self.tmp / "inst", skills_dir=FIXTURE_TRANSPORTS,
                              exit_code=2, key="house_rules.blocker_chase.start")

    def test_settings_never_aliases_the_defaults(self):
        s = manifest.settings(MINIMAL)
        s["house_rules"]["blocker_chase"]["days"].append("sun")
        s["house_rules"]["times"]["cities"].clear()
        self.assertEqual(manifest.DEFAULT_HOUSE_RULES, DESIGN_HOUSE_RULES)


def template():
    return read_json(REPO / "templates" / "fleet.example.json")


def paths_of(d, prefix=""):
    """Every dotted key in `d`, with `[]` for the fields of list items (comments stripped)."""
    out = set()
    for k, v in d.items():
        key = f"{prefix}{k}"
        out.add(key)
        if isinstance(v, dict) and prefix != "conventions.":  # a convention's value is data
            out |= paths_of(v, key + ".")
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for x in v:
                out |= paths_of(x, key + "[].")
    return out


# The template's placeholder form, written out here and not read from manifest.py:
# one <...> as a whole, a space inside, no @.
PLACEHOLDER_FORM = r"<[^<>@]*\s[^<>@]*>"


def placeholder_keys(d, prefix=""):
    """The dotted key of every string in `d` in the template's placeholder form
    (comments stripped)."""
    out = []
    items = enumerate(d) if isinstance(d, list) else d.items()
    for k, v in items:
        key = f"{prefix}[{k}]" if isinstance(d, list) else (f"{prefix}.{k}" if prefix else k)
        if isinstance(v, (dict, list)):
            out += placeholder_keys(v, key)
        elif isinstance(v, str) and re.fullmatch(PLACEHOLDER_FORM, v):
            out.append(key)
    return out


class TemplateTest(IsolatedTest):
    def test_unedited_template_is_refused_naming_its_first_placeholder(self):
        # SETUP's copy of the template must not pass `fleet settings` unedited.
        m = manifest.strip_comments(template())
        keys = placeholder_keys(m)
        self.assertTrue(keys, "the template marks no value as a placeholder to replace")
        write_json(self.tmp / "inst" / ".claude" / "fleet.json", template())
        self.assertFleetError(ManifestError, manifest.load, self.tmp / "inst", skills_dir=FIXTURE_TRANSPORTS,
                              exit_code=2, key=keys[0])

    def test_template_loads_once_its_placeholders_are_filled(self):
        # The control for the refusal above: the template's only defect is its
        # placeholders, so filling them in is all a valid manifest still needs.
        def fill(v):
            if isinstance(v, dict):
                return {k: fill(x) for k, x in v.items()}
            if isinstance(v, list):
                return [fill(x) for x in v]
            return "filled-in" if isinstance(v, str) and re.fullmatch(PLACEHOLDER_FORM, v) else v
        write_json(self.tmp / "inst" / ".claude" / "fleet.json", fill(template()))
        manifest.load(self.tmp / "inst", skills_dir=FIXTURE_TRANSPORTS)

    def test_template_has_every_schema_key(self):
        have = paths_of(manifest.strip_comments(template()))
        self.assertEqual(sorted(set(manifest.schema_keys()) - have), [])
        self.assertEqual(sorted(have - set(manifest.schema_keys())), [])

    def test_template_comments_every_object(self):
        def walk(d, key):
            if isinstance(d, dict):
                if not key.startswith("conventions."):  # a convention's value is data, not a section
                    self.assertIn("_comment", d, key or "top level")
                for k, v in d.items():
                    if not k.startswith("_"):
                        walk(v, f"{key}.{k}" if key else k)
        walk(template(), "")

    def test_template_is_ascii(self):
        (REPO / "templates" / "fleet.example.json").read_bytes().decode("ascii")


class ConventionsDocTest(unittest.TestCase):
    TEXT = (REPO / "CONVENTIONS.md").read_text(encoding="utf-8")

    def test_is_ascii(self):
        self.TEXT.encode("ascii")

    def test_names_every_convention_key(self):
        for k in manifest.CONVENTION_KEYS:
            self.assertIn(f"| `{k}` |", self.TEXT, k)

    def test_states_every_house_rule_with_its_default(self):
        leaves = {"questions_per_message": ("questions_per_message",),
                  "state_the_fact": ("state_the_fact",), "ascii_skill_prose": ("ascii_skill_prose",),
                  "times.cities": ("times", "cities")}
        leaves.update({f"blocker_chase.{k}": ("blocker_chase", k) for k in manifest.BLOCKER_KEYS})
        rows = dict(re.findall(r"^\| `house_rules\.([a-z_.]+)` \| `(.+?)` \|", self.TEXT, re.M))
        self.assertEqual(sorted(rows), sorted(leaves), "one row per house rule, no more")
        for name, path in leaves.items():
            want = manifest.DEFAULT_HOUSE_RULES
            for p in path:
                want = want[p]
            self.assertEqual(json.loads(rows[name]), want, name)



if __name__ == "__main__":
    unittest.main()
