"""Tests for the fleetlib exception contract: each class's exit code, variable and key.

Callers (the `fleet` command, every fleet script) print str(err) and exit
err.exit_code, so these codes ARE the command's exit codes: 2 refused, 3
environment fault.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import fleetlib  # noqa: E402
from fleetlib import (DescriptorError, EnvironmentFault, FleetError,  # noqa: E402
                      ManifestError, Refused)


class ErrorsTest(unittest.TestCase):
    def test_exit_code_constants(self):
        self.assertEqual((fleetlib.OK, fleetlib.DRIFT, fleetlib.REFUSED, fleetlib.FAULT), (0, 1, 2, 3))

    def test_class_exit_codes(self):
        self.assertEqual(EnvironmentFault("m").exit_code, 3)
        self.assertEqual(DescriptorError("m").exit_code, 3)
        self.assertEqual(Refused("m").exit_code, 2)
        self.assertEqual(ManifestError("m").exit_code, 2)

    def test_hierarchy(self):
        for cls in (EnvironmentFault, Refused, ManifestError, DescriptorError):
            self.assertTrue(issubclass(cls, FleetError), cls)
        self.assertTrue(issubclass(ManifestError, Refused))
        self.assertTrue(issubclass(DescriptorError, EnvironmentFault))

    def test_variable_and_key(self):
        e = EnvironmentFault("no install", variable="FLEET_CONTEXT_ROOT", key="k.x")
        self.assertEqual((e.variable, e.key, e.message), ("FLEET_CONTEXT_ROOT", "k.x", "no install"))
        self.assertEqual(str(e), "no install (set FLEET_CONTEXT_ROOT)")
        self.assertEqual(str(EnvironmentFault("set FLEET_X first", variable="FLEET_X")), "set FLEET_X first",
                         "a message that already names the variable is not repeated")
        self.assertEqual(str(Refused("bad")), "bad")


if __name__ == "__main__":
    unittest.main()
