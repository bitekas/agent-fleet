"""Tests for fleetlib.expand: ~, $VAR, ${VAR}, ${VAR:-default} with nesting."""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import expand  # noqa: E402

HOME = "/tmp/fleet-t3a-home"


def x(s, **env):
    return expand.value(s, {"HOME": HOME, **env})


class ExpandTest(unittest.TestCase):
    def test_tilde(self):
        self.assertEqual(x("~"), HOME)
        self.assertEqual(x("~/k/f"), HOME + "/k/f")
        self.assertEqual(x("a/~/b"), "a/~/b", "only a LEADING ~ expands")

    def test_plain_and_braced_variables(self):
        self.assertEqual(x("$A/f", A="/a"), "/a/f")
        self.assertEqual(x("${A}x", A="/a"), "/ax")
        self.assertEqual(x("$A_B", A="/a", A_B="/ab"), "/ab", "a name runs to its last name character")

    def test_unset_variable_stays_literal(self):
        self.assertEqual(x("$NOPE/f"), "$NOPE/f")
        self.assertEqual(x("${NOPE}/f"), "${NOPE}/f")

    def test_default_when_unset_or_empty(self):
        self.assertEqual(x("${A:-/d}"), "/d")
        self.assertEqual(x("${A:-/d}", A=""), "/d", "an EMPTY variable takes the default (shell :-)")
        self.assertEqual(x("${A:-/d}", A="/a"), "/a")
        self.assertEqual(x("${A:-}x"), "x")

    def test_one_level_of_nesting(self):
        s = "${A:-${B:-/x}}"
        self.assertEqual(x(s), "/x")
        self.assertEqual(x(s, B="/b"), "/b")
        self.assertEqual(x(s, A="/a", B="/b"), "/a")
        self.assertEqual(x(s, A="", B=""), "/x")
        self.assertEqual(x(s + "/key", B="/b"), "/b/key", "text after the closing brace survives")

    def test_two_levels_of_nesting(self):
        self.assertEqual(x("${A:-${B:-${C:-/c}}}/k"), "/c/k")
        self.assertEqual(x("${A:-${B:-${C:-/c}}}/k", C="/z"), "/z/k")

    def test_default_holds_variables_and_tilde(self):
        self.assertEqual(x("${A:-$HOME/.s}/k"), HOME + "/.s/k")
        self.assertEqual(x("${A:-~/.s}/k"), HOME + "/.s/k", "a leading ~ expands after the variables")
        self.assertEqual(x("${A}/k", A="~/v"), HOME + "/v/k", "a variable set to ~/... expands too")

    def test_environment_values_are_not_rescanned(self):
        self.assertEqual(x("${A:-/d}", A="$HOME"), "$HOME")
        self.assertEqual(x("$A", A="${B:-/b}", B="/no"), "${B:-/b}")

    def test_malformed_text_stays_literal(self):
        self.assertEqual(x("${A:-/d"), "${A:-/d")
        self.assertEqual(x("$"), "$")
        self.assertEqual(x("$1/x"), "$1/x")
        self.assertEqual(x("${-}"), "${-}")

    def test_depth_cap_leaves_deep_nesting_literal(self):
        deep = "${A:-" * (expand.MAX_DEPTH + 2) + "/x" + "}" * (expand.MAX_DEPTH + 2)
        out = x(deep)
        self.assertIn("${A:-", out, "beyond MAX_DEPTH the text stays literal")

    def test_defaults_to_os_environ(self):
        os.environ["FLEET_T3A_EXPAND"] = "/from-env"
        try:
            self.assertEqual(expand.value("${FLEET_T3A_EXPAND:-/d}"), "/from-env")
        finally:
            del os.environ["FLEET_T3A_EXPAND"]

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            expand.value(None)


if __name__ == "__main__":
    unittest.main()
