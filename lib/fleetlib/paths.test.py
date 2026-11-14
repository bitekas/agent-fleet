"""Tests for fleetlib.paths: host settings, install-root steps 1-4, skill context,
config-relative paths, the secrets-directory order, and the realpath rule."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import EnvironmentFault, Refused, paths  # noqa: E402
from fleetlib._testkit import (FIXTURE_TRANSPORTS, MINIMAL, REPO, IsolatedTest,  # noqa: E402
                               make_install, run_python, write_json)

HOST_OK = {"schema": 1, "agents_root": "", "fleet_checkout": "/tmp/fleet-t3a/fleet",
           "claims_dir": "/tmp/fleet-t3a/claims"}


def git_init(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return path


class FleetRootTest(IsolatedTest):
    def test_fleet_root_is_the_real_tree_when_imported_through_a_link(self):
        # 4.4's trap: imported through a link, abspath(__file__) keeps the link path and
        # parents[2] is the link's parent, not the fleet tree. Only realpath gives REPO.
        link = self.tmp / "linked-lib"
        link.symlink_to(REPO / "lib")
        r = run_python("import sys; sys.path.insert(0, sys.argv[1]); "
                       "import fleetlib.paths as p; print(p.fleet_root())", link)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str(REPO))

    def test_fleet_root_in_process(self):
        self.assertEqual(paths.fleet_root(), REPO)


class HostTest(IsolatedTest):
    def host_file(self, data, path=None):
        path = path or self.tmp / "host.json"
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            write_json(path, data)
        return path

    def test_reads_fleet_host_config(self):
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file({**HOST_OK, "agents_root": "/tmp/a"}))
        self.assertEqual(paths.host()["agents_root"], "/tmp/a")

    def test_default_path_is_under_home(self):
        self.host_file({**HOST_OK, "agents_root": "/tmp/b"},
                       self.home / ".config" / "agent-fleet" / "host.json")
        self.assertEqual(paths.host()["agents_root"], "/tmp/b")

    def test_missing_is_exit_3_saying_fleet_install(self):
        err = self.assertFleetError(EnvironmentFault, paths.host, exit_code=3, variable="FLEET_HOST_CONFIG")
        self.assertIn("fleet install", str(err))

    def test_invalid_json_is_exit_3(self):
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file("{not json"))
        self.assertFleetError(EnvironmentFault, paths.host, exit_code=3, variable="FLEET_HOST_CONFIG")

    def test_missing_key_is_named(self):
        data = {**HOST_OK, "agents_root": "/tmp/c"}
        del data["claims_dir"]
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file(data))
        self.assertFleetError(EnvironmentFault, paths.host, exit_code=3, key="claims_dir")

    def test_wrong_schema_is_named(self):
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file({**HOST_OK, "agents_root": "/a", "schema": 2}))
        self.assertFleetError(EnvironmentFault, paths.host, exit_code=3, key="schema")

    def test_optional_settings_default_and_are_read(self):
        os.environ["FLEET_HOST_CONFIG"] = str(self.tmp / "absent.json")
        self.assertEqual(paths.host_option("launchd_prefix"), "com.agent-fleet",
                         "no host settings file: the default")
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file({**HOST_OK, "agents_root": "/a"}))
        self.assertEqual(paths.host_option("launchd_prefix"), "com.agent-fleet")
        self.assertEqual(paths.host_option("launchd_domain"), "gui")
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file({**HOST_OK, "agents_root": "/a",
                                                              "launchd_prefix": "com.agent-fleet-test",
                                                              "launchd_domain": "user"}))
        self.assertEqual(paths.host_option("launchd_prefix"), "com.agent-fleet-test")
        self.assertEqual(paths.host_option("launchd_domain"), "user")
        self.assertEqual(paths.host()["agents_root"], "/a", "the optional keys leave the required ones alone")

    def test_an_optional_setting_that_breaks_its_rule_is_named(self):
        # Each value would put a label or a domain target together wrongly: no dot,
        # a path separator, a leading dot, a domain launchd does not have, not a string.
        for key, bad in (("launchd_prefix", "agentfleet"), ("launchd_prefix", "com/agent"),
                         ("launchd_prefix", ".com.agent"), ("launchd_prefix", 7),
                         ("launchd_domain", "system"), ("launchd_domain", "gui/501")):
            os.environ["FLEET_HOST_CONFIG"] = str(self.host_file({**HOST_OK, "agents_root": "/a", key: bad}))
            self.assertFleetError(EnvironmentFault, paths.host, exit_code=3, key=key)
            self.assertFleetError(EnvironmentFault, paths.host_option, key, exit_code=3, key=key)

    def test_a_broken_host_file_is_never_read_as_the_default(self):
        os.environ["FLEET_HOST_CONFIG"] = str(self.host_file("{not json"))
        self.assertFleetError(EnvironmentFault, paths.host_option, "launchd_prefix", exit_code=3,
                              variable="FLEET_HOST_CONFIG")


@unittest.skipIf(os.geteuid() == 0, "root may change every path: nothing here could be protected")
class ChangeableTest(IsolatedTest):
    """The rule verify-privileges.py FAILs by and `fleet install --part agents`
    refuses by. The protected side is a root-owned tree every Linux and macOS
    machine has; the exposed side is this test's own files."""

    PROTECTED = "/etc/pam.d"

    def setUp(self):
        super().setUp()
        if not os.path.isdir(self.PROTECTED) or os.stat(self.PROTECTED).st_uid != 0:
            self.skipTest(f"{self.PROTECTED} is not a root-owned directory here")
        # Under /tmp, sticky and root's on Linux and macOS alike: the default temp
        # directory (macOS's /var/folders/.../T) is this user's and writable, so
        # nothing below it could be protected from this user.
        self.sticky = Path(os.path.realpath(tempfile.mkdtemp(prefix="fleet-paths-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.sticky, ignore_errors=True)
        self.tree = self.sticky / "fleet"
        (self.tree / "lib").mkdir(parents=True)
        (self.tree / "lib" / "x.py").write_text("x\n")
        self.addCleanup(lambda: [p.chmod(0o755) for p in (self.tree / "lib", self.tree)])

    def test_a_root_owned_tree_is_not_changeable(self):
        self.assertIsNone(paths.changeable(self.PROTECTED))
        self.assertIsNone(paths.tree_changeable(self.PROTECTED))

    def test_an_owned_read_only_file_is_changeable_by_ownership(self):
        f = self.tree / "lib" / "x.py"
        f.chmod(0o444)
        self.assertFalse(os.access(f, os.W_OK), "control: the file is read-only by mode")
        self.assertIn("owns", paths.changeable(f))

    def test_the_tree_form_finds_one_writable_file_deep_inside(self):
        # The walk itself: this process plays another uid for ownership (access
        # checks stay real), and every directory from the tree up to the sticky
        # /tmp is read-only by mode. Then only lib/x.py's mode can make the
        # tree changeable, and the finding must name it.
        uid = os.geteuid() + 4242
        for p in (self.tree / "lib", self.tree, self.sticky):
            p.chmod(0o555)
        self.addCleanup(self.sticky.chmod, 0o755)
        x = self.tree / "lib" / "x.py"
        with mock.patch.object(paths.os, "geteuid", return_value=uid):
            self.assertIsNone(paths.changeable(self.tree), "control: the root and its chain are protected")
            x.chmod(0o644)
            self.assertEqual(paths.tree_changeable(self.tree), f"may write {x}")
            x.chmod(0o444)
            self.assertIsNone(paths.tree_changeable(self.tree))
            (self.tree / "lib").chmod(0o755)
            self.assertTrue(paths.tree_changeable(self.tree).startswith(f"may write {self.tree / 'lib'}"))

    def test_a_path_behind_a_directory_this_user_cannot_search_is_judged_from_above(self):
        # Another user's private home (here root's): its files cannot be reached,
        # so only a writable directory above could change them, and there is none.
        private = next((d for d in ("/root", "/var/root")
                        if os.path.isdir(d) and os.stat(d).st_uid == 0 and not os.access(d, os.X_OK)), None)
        if private is None:
            self.skipTest("no root-owned home this user cannot search")
        hidden = os.path.join(private, ".config", "agent-fleet", "identities.json")
        with self.assertRaises(PermissionError, msg="control: the path really cannot be inspected"):
            os.lstat(hidden)
        self.assertIsNone(paths.changeable(hidden))

    def test_a_link_in_a_writable_directory_is_changeable(self):
        link = self.tmp / "fleet-link"
        link.symlink_to(self.PROTECTED)
        self.assertIsNone(paths.changeable(os.path.realpath(link)), "control: the target is protected")
        self.assertIn(str(link), paths.changeable(link))


class InstallRootTest(IsolatedTest):
    def agents(self, agents_root=None):
        """A fleet host whose agents root is tmp/agents; returns that root."""
        root = self.tmp / "agents"
        root.mkdir(exist_ok=True)
        write_json(self.tmp / "host.json", {**HOST_OK, "agents_root": str(agents_root or root)})
        os.environ["FLEET_HOST_CONFIG"] = str(self.tmp / "host.json")
        return root

    # step 1
    def test_step1_context_root(self):
        inst = make_install(self.tmp / "inst")
        os.environ["FLEET_CONTEXT_ROOT"] = str(inst)
        self.assertEqual(paths.install_root(), inst)

    def test_step1_relative_context_root_resolves_against_the_working_directory(self):
        inst = make_install(self.tmp / "inst")
        os.environ["FLEET_CONTEXT_ROOT"] = "inst"
        self.assertEqual(paths.install_root(), inst)

    def test_step1_set_without_manifest_is_exit_3_and_never_falls_through(self):
        # A git tree holding a manifest (step 2 would answer) proves no fall-through.
        repo = make_install(git_init(self.tmp / "repo"))
        (self.tmp / "empty").mkdir()
        os.environ["FLEET_CONTEXT_ROOT"] = str(self.tmp / "empty")
        self.assertFleetError(EnvironmentFault, paths.install_root, repo,
                              exit_code=3, variable="FLEET_CONTEXT_ROOT")

    # step 2
    def test_step2_git_top_level_holding_a_manifest(self):
        repo = make_install(git_init(self.tmp / "repo"))
        deep = repo / "a" / "b"
        deep.mkdir(parents=True)
        os.chdir(deep)
        self.assertEqual(paths.install_root(), repo)
        os.chdir(self.tmp)
        self.assertEqual(paths.install_root(cwd=deep), repo, "the cwd argument is honoured")

    def test_step2_worktree_style_git_file(self):
        repo = make_install(self.tmp / "wt")
        (repo / ".git").write_text("gitdir: /tmp/fleet-t3a-nowhere\n", encoding="utf-8")
        (repo / "sub").mkdir()
        self.assertEqual(paths.install_root(cwd=repo / "sub"), repo)

    def test_step2_ignores_an_exported_git_dir(self):
        # A hook exports GIT_DIR; `git rev-parse --show-toplevel` then answers the
        # directory it was run in (here repo/sub, which holds no manifest), so only a
        # lookup that ignores GIT_DIR finds repo. Run from the top level itself, the
        # two would agree and this test could not tell them apart.
        repo = make_install(git_init(self.tmp / "repo"))
        (repo / "sub").mkdir()
        other = git_init(self.tmp / "other")
        os.environ["GIT_DIR"] = str(other / ".git")
        self.assertEqual(paths.install_root(cwd=repo / "sub"), repo)

    def test_step2_beats_step3(self):
        root = self.agents()
        make_install(root / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        repo = make_install(git_init(self.tmp / "repo"))
        self.assertEqual(paths.install_root(cwd=repo), repo)

    def test_git_top_false_skips_step2(self):
        # The leak gate's seam: its working tree is the repository under scan, so a
        # manifest committed there must not answer. The default call answers step 2
        # from the same tree (the control that the tree WOULD answer), and with
        # git_top=False the answer is step 3's, or exit 3 when step 3 cannot apply.
        root = self.agents()
        proj = make_install(root / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        repo = make_install(git_init(self.tmp / "repo"))
        (repo / "sub").mkdir()
        os.chdir(repo / "sub")
        self.assertEqual(paths.install_root(), repo, "control: step 2 answers from this tree")
        self.assertEqual(paths.install_root(git_top=False), proj)
        self.assertEqual(paths.install_root(cwd=repo, git_top=False), proj)
        del os.environ["CLAUDE_CONFIG_DIR"]
        err = self.assertFleetError(EnvironmentFault, paths.install_root, git_top=False,
                                    exit_code=3, variable="FLEET_CONTEXT_ROOT")
        self.assertIn("no install manifest resolves", str(err))
        self.assertNotIn("git tree", str(err))

    # step 3
    def test_step3_agent_home_project(self):
        root = self.agents()
        proj = make_install(root / "ada" / "proj")
        (root / "ada" / ".claude").mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        self.assertEqual(paths.install_root(), proj)

    def test_step3_from_a_git_tree_without_a_manifest(self):
        root = self.agents()
        proj = make_install(root / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        repo = git_init(self.tmp / "fleet-worktree")
        self.assertEqual(paths.install_root(cwd=repo), proj)

    def test_step3_agents_root_named_through_a_link(self):
        root = self.tmp / "agents"
        root.mkdir()
        (self.tmp / "agents-link").symlink_to(root)
        self.agents(agents_root=self.tmp / "agents-link")
        proj = make_install(root / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        self.assertEqual(paths.install_root(), proj)

    def test_step3_zero_manifests_is_exit_3(self):
        root = self.agents()
        (root / "ada" / ".claude").mkdir(parents=True)
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        err = self.assertFleetError(EnvironmentFault, paths.install_root,
                                    exit_code=3, variable="FLEET_CONTEXT_ROOT")
        self.assertIn("0 install manifests", str(err))

    def test_step3_two_manifests_in_one_home_is_exit_3(self):
        root = self.agents()
        make_install(root / "ada" / "proj-one")
        make_install(root / "ada" / "proj-two")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "ada" / ".claude")
        err = self.assertFleetError(EnvironmentFault, paths.install_root,
                                    exit_code=3, variable="FLEET_CONTEXT_ROOT")
        self.assertIn("2 install manifests", str(err))

    def test_step3_home_not_a_direct_child_of_agents_root_is_exit_3(self):
        root = self.agents()
        make_install(root / "team" / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "team" / "ada" / ".claude")
        err = self.assertFleetError(EnvironmentFault, paths.install_root,
                                    exit_code=3, variable="FLEET_CONTEXT_ROOT")
        self.assertIn("not a direct child", str(err))

    def test_step3_without_host_settings_is_exit_3_naming_both(self):
        make_install(self.tmp / "agents" / "ada" / "proj")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "agents" / "ada" / ".claude")
        err = self.assertFleetError(EnvironmentFault, paths.install_root,
                                    exit_code=3, variable="FLEET_CONTEXT_ROOT")
        self.assertIn("fleet install", str(err))

    # step 4
    def test_step4_nothing_resolves_is_exit_3(self):
        self.assertFleetError(EnvironmentFault, paths.install_root, exit_code=3, variable="FLEET_CONTEXT_ROOT")

    def test_step4_names_the_git_tree_it_searched_or_says_there_is_none(self):
        # The step-2 clause of the message: a tree without a manifest is named, and a
        # working directory outside every tree says so - never "no git tree holds no
        # manifest", which reads as the opposite of what happened.
        repo = git_init(self.tmp / "repo")
        os.chdir(repo)
        err = self.assertFleetError(EnvironmentFault, paths.install_root, exit_code=3,
                                    variable="FLEET_CONTEXT_ROOT")
        self.assertIn(f"the git tree {repo} holds no .claude/fleet.json", str(err))
        os.chdir(self.tmp)
        err = self.assertFleetError(EnvironmentFault, paths.install_root, exit_code=3,
                                    variable="FLEET_CONTEXT_ROOT")
        self.assertIn("the working directory is in no git tree", str(err))
        self.assertNotIn("holds no .claude/fleet.json", str(err))
        err = self.assertFleetError(EnvironmentFault, paths.install_root, self.tmp, exit_code=3,
                                    variable="FLEET_CONTEXT_ROOT")
        self.assertIn(f"{self.tmp} is in no git tree", str(err))


class SkillContextTest(IsolatedTest):
    def test_skill_context_is_under_the_install_root(self):
        inst = make_install(self.tmp / "inst")
        os.environ["FLEET_CONTEXT_ROOT"] = str(inst)
        self.assertEqual(paths.skill_context("agent-revive"), inst / ".claude" / "skills" / "agent-revive")

    def test_skill_context_follows_install_root_failures(self):
        self.assertFleetError(EnvironmentFault, paths.skill_context, "agent", exit_code=3,
                              variable="FLEET_CONTEXT_ROOT")

    def test_bad_skill_names_are_refused(self):
        os.environ["FLEET_CONTEXT_ROOT"] = str(make_install(self.tmp / "inst"))
        for bad in ("", "../agent", "a/b", ".hidden", None):
            self.assertFleetError(Refused, paths.skill_context, bad, exit_code=2)


class ResolveConfigPathTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = write_json(self.tmp / "inst" / ".claude" / "skills" / "rg" / "config.json", {})
        (self.tmp / "elsewhere").mkdir()
        os.chdir(self.tmp / "elsewhere")

    def test_relative_resolves_against_the_config_files_directory(self):
        self.assertEqual(paths.resolve_config_path("../../skill-data/log.jsonl", self.cfg),
                         self.tmp / "inst" / ".claude" / "skill-data" / "log.jsonl")
        self.assertEqual(paths.resolve_config_path("state.json", str(self.cfg)),
                         self.cfg.parent / "state.json")

    def test_absolute_is_unchanged(self):
        self.assertEqual(paths.resolve_config_path("/tmp/fleet-t3a-abs/x", self.cfg), Path("/tmp/fleet-t3a-abs/x"))

    def test_value_is_expanded_first(self):
        self.assertEqual(paths.resolve_config_path("~/k", self.cfg), self.home / "k")
        self.assertEqual(paths.resolve_config_path("${FLEET_T3A_UNSET:-sub}/f", self.cfg), self.cfg.parent / "sub" / "f")

    def test_config_reached_through_a_link_resolves_physically(self):
        link = self.tmp / "skills-link"
        link.symlink_to(self.cfg.parent)
        self.assertEqual(paths.resolve_config_path("../../x", link / "config.json"),
                         self.tmp / "inst" / ".claude" / "x")


class ResolveRepoPathTest(IsolatedTest):
    """resolve_repo_path(): a config value that names a file in the install's
    repository resolves against the install root, never against the config file's
    directory or the working directory. The control for every case is the same value
    through resolve_config_path, which lands somewhere else."""

    def setUp(self):
        super().setUp()
        self.root = make_install(self.tmp / "inst")
        self.cfg = write_json(self.root / ".claude" / "skills" / "rg" / "config.json", {})
        os.environ["FLEET_CONTEXT_ROOT"] = str(self.root)
        (self.tmp / "elsewhere").mkdir()
        os.chdir(self.tmp / "elsewhere")

    def test_relative_resolves_against_the_install_root(self):
        self.assertEqual(paths.resolve_repo_path("scripts/build.sh"), self.root / "scripts" / "build.sh")
        self.assertNotEqual(paths.resolve_config_path("scripts/build.sh", self.cfg),
                            self.root / "scripts" / "build.sh", "the two resolvers agree, so this proves nothing")

    def test_a_given_root_wins(self):
        other = make_install(self.tmp / "other")
        self.assertEqual(paths.resolve_repo_path("docs/x.md", other), other / "docs" / "x.md")

    def test_absolute_is_unchanged_and_the_value_is_expanded_first(self):
        self.assertEqual(paths.resolve_repo_path("/tmp/fleet-t3a-abs/x"), Path("/tmp/fleet-t3a-abs/x"))
        self.assertEqual(paths.resolve_repo_path("~/k"), self.home / "k")
        self.assertEqual(paths.resolve_repo_path("${FLEET_T3A_UNSET:-sub}/f"), self.root / "sub" / "f")

    def test_a_root_reached_through_a_link_resolves_physically(self):
        link = self.tmp / "inst-link"
        link.symlink_to(self.root)
        self.assertEqual(paths.resolve_repo_path("a/../b", link), self.root / "b")

    def test_no_install_is_install_roots_fault(self):
        del os.environ["FLEET_CONTEXT_ROOT"]
        self.assertFleetError(EnvironmentFault, paths.resolve_repo_path, "x", exit_code=3,
                              variable="FLEET_CONTEXT_ROOT")

    def test_an_absolute_value_needs_no_install(self):
        # As resolve_config_path never reads its config file's directory for one: the
        # install root is looked up only for a value that needs it.
        del os.environ["FLEET_CONTEXT_ROOT"]
        self.assertEqual(paths.resolve_repo_path("/tmp/fleet-t3a-abs/x"), Path("/tmp/fleet-t3a-abs/x"))
        self.assertEqual(paths.resolve_repo_path("~/k"), self.home / "k")


class SecretsDirTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        os.environ["FLEET_TRANSPORTS_DIR"] = str(FIXTURE_TRANSPORTS)

    def install(self, secrets=None):
        m = dict(MINIMAL)
        if secrets is not None:
            m["secrets"] = secrets
        os.environ["FLEET_CONTEXT_ROOT"] = str(make_install(self.tmp / "inst", m))

    def test_1_fleet_secrets_dir_wins(self):
        self.install({"legacy_env": "FLEET_T3A_LEGACY", "default_dir": "/tmp/fleet-t3a-default"})
        os.environ["FLEET_T3A_LEGACY"] = "/tmp/fleet-t3a-legacy"
        os.environ["FLEET_SECRETS_DIR"] = "/tmp/fleet-t3a-fleet"
        self.assertEqual(paths.secrets_dir(), Path("/tmp/fleet-t3a-fleet"))

    def test_1_fleet_secrets_dir_needs_no_install(self):
        os.environ["FLEET_SECRETS_DIR"] = "~/s"
        self.assertEqual(paths.secrets_dir(), self.home / "s")

    def test_2_legacy_variable_named_by_the_manifest(self):
        self.install({"legacy_env": "FLEET_T3A_LEGACY", "default_dir": "/tmp/fleet-t3a-default"})
        os.environ["FLEET_T3A_LEGACY"] = "/tmp/fleet-t3a-legacy"
        self.assertEqual(paths.secrets_dir(), Path("/tmp/fleet-t3a-legacy"))

    def test_2_empty_variables_count_as_unset(self):
        self.install({"legacy_env": "FLEET_T3A_LEGACY", "default_dir": "/tmp/fleet-t3a-default"})
        os.environ["FLEET_SECRETS_DIR"] = ""
        os.environ["FLEET_T3A_LEGACY"] = ""
        self.assertEqual(paths.secrets_dir(), Path("/tmp/fleet-t3a-default"))

    def test_3_default_dir(self):
        self.install({"legacy_env": "FLEET_T3A_LEGACY", "default_dir": "~/.example-secrets"})
        self.assertEqual(paths.secrets_dir(), self.home / ".example-secrets")

    def test_3_null_legacy_env_reads_no_variable(self):
        self.install({"legacy_env": None, "default_dir": "/tmp/fleet-t3a-default"})
        os.environ["FLEET_T3A_LEGACY"] = "/tmp/fleet-t3a-legacy"
        self.assertEqual(paths.secrets_dir(), Path("/tmp/fleet-t3a-default"))

    def test_4_fleet_default(self):
        self.install()
        self.assertEqual(paths.secrets_dir(), self.home / ".fleet-secrets")

    def test_no_install_and_no_variable_is_exit_3(self):
        self.assertFleetError(EnvironmentFault, paths.secrets_dir, exit_code=3, variable="FLEET_CONTEXT_ROOT")

    def test_the_library_names_no_install_variable(self):
        # The legacy variable's name comes from the manifest, so the only *_SECRETS_DIR
        # the library source may spell is the fleet's own. The positive half proves the
        # pattern finds a known-present name, so an empty finding is not a broken grep.
        pat = re.compile(r"\b[A-Z][A-Z0-9_]*_SECRETS_DIR\b")
        lib = Path(paths.__file__).parent
        sources = [p for p in sorted(lib.glob("*.py")) if not p.name.endswith(".test.py")
                   and p.name != "_testkit.py"]
        self.assertGreaterEqual(len(sources), 5, sources)
        found = set()
        for p in sources:
            found |= set(pat.findall(p.read_text(encoding="utf-8")))
        self.assertIn("FLEET_SECRETS_DIR", found)
        self.assertEqual(found, {"FLEET_SECRETS_DIR"})


if __name__ == "__main__":
    unittest.main()
