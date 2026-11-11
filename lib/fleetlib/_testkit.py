"""Shared scaffolding for the fleetlib tests (not part of the library's API).

Every test runs with:
  * the fleet's environment variables scrubbed - tests/run-all.sh exports
    FLEET_CONTEXT_ROOT and FLEET_HOST_CONFIG for every test, and an agent
    session exports CLAUDE_CONFIG_DIR; any of them left in place would answer
    a lookup the test means to exercise;
  * HOME pointed at a directory under the test's temporary root, so no default
    path (~/.config/agent-fleet/host.json, ~/.fleet-secrets) reaches the real one;
  * the working directory set to that temporary root, which must not lie inside
    a git tree (a TMPDIR inside a checkout would hand install_root step 2 a top
    level the test did not make) - checked, not assumed.
The test files set sys.dont_write_bytecode before importing fleetlib, so no
__pycache__ is written into the tree under test.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parents[2]
FIXTURES = REPO / "tests" / "fixtures"
FIXTURE_INSTALL = FIXTURES / "install"
FIXTURE_TRANSPORTS = FIXTURES / "transports"
FIXTURE_HOST = FIXTURES / "host.json"
SCRUB = ("FLEET_CONTEXT_ROOT", "FLEET_HOST_CONFIG", "FLEET_SECRETS_DIR",
         "FLEET_TRANSPORTS_DIR", "CLAUDE_CONFIG_DIR", "GIT_DIR", "GIT_WORK_TREE")

MINIMAL = {
    "schema": 1,
    "fleet": {"repo": "https://example.com/example/agent-fleet.git", "min_tag": "v1.0.0"},
    "skills": ["chat-transport", "slack-communication"],
    "transports": {"enabled": ["slack"], "default": "slack"},
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def make_install(root, manifest=None):
    """`root` with `.claude/fleet.json` holding `manifest` (default MINIMAL)."""
    write_json(Path(root) / ".claude" / "fleet.json", MINIMAL if manifest is None else manifest)
    return Path(root)


def run_python(code, *args, env=None, cwd=None):
    """Run `code` in a child interpreter (-B: no bytecode written)."""
    return subprocess.run([sys.executable, "-B", "-c", code, *map(str, args)],
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=60)


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)
        self._saved_cwd = os.getcwd()
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="fleet-t3a-")))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self._restore)
        for d in (self.tmp, *self.tmp.parents):
            if os.path.lexists(d / ".git"):
                self.fail(f"the temporary root {self.tmp} lies inside the git tree {d}; "
                          "point TMPDIR outside any checkout")
        for k in SCRUB:
            os.environ.pop(k, None)
        self.home = self.tmp / "home"
        self.home.mkdir()
        os.environ["HOME"] = str(self.home)
        os.chdir(self.tmp)

    def _restore(self):
        os.chdir(self._saved_cwd)
        os.environ.clear()
        os.environ.update(self._saved_env)

    def assertFleetError(self, cls, fn, *args, exit_code, variable=None, key=None, **kwargs):
        """`fn(*args)` raises exactly a `cls` with these attributes; returns it."""
        with self.assertRaises(cls) as cm:
            fn(*args, **kwargs)
        err = cm.exception
        self.assertEqual(err.exit_code, exit_code, f"exit code of {err!r}")
        if variable is not None:
            self.assertEqual(err.variable, variable, f"variable of {err!r}")
            self.assertIn(variable, str(err))
        if key is not None:
            self.assertEqual(err.key, key, f"key of: {err}")
            self.assertIn(key, str(err))
        return err
