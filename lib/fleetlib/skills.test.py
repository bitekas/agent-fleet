"""Tests for fleetlib.skills: reading a SKILL.md's `## Install` section.

The control for every refusal: BASE_A and BASE_B parse (test_bases_parse), and
each refused text below is one of them with ONE mutation, so the refusal is
caused by that mutation and not by something else in the text. Each refusal
also asserts the words of its own reason: a refusal for the wrong reason (a
fenced heading counted, then refused as a second paragraph) is a red, not a
pass, because assertRaises alone cannot tell the two apart.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import DRIFT, FleetError, skills  # noqa: E402
from fleetlib.skills import InstallSectionError, install_section  # noqa: E402

FRONT = "---\nname: zz\nversion: 1\ndescription: >\n  A test skill.\nrequires_install: false\n---\n\n# zz\n\nIntro.\n\n"

BASE_A = FRONT + "## 1. Rules\n\nA rule.\n\n## Install\n\nNothing to install.\n"

BASE_B = (FRONT + "## 1. Rules\n\nA rule.\n\n## Install\n\n"
          "**Asks for:** the bot token's path, and\nthe channel id.\n\n"
          "**Writes:** `config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`.\n\n"
          "**Steps:** `installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.\n\n"
          "An optional paragraph after Steps.\n")


def mutate(base, old, new):
    assert base.count(old) == 1, f"the mutation's anchor {old!r} does not occur exactly once"
    return base.replace(old, new)


class ParseTest(unittest.TestCase):
    def refused(self, text, *needles):
        with self.assertRaises(InstallSectionError) as cm:
            install_section(text)
        for n in needles:
            self.assertIn(n, str(cm.exception), "refused, but not for this reason")
        return cm.exception

    def test_bases_parse(self):
        self.assertEqual(install_section(BASE_A).form, "nothing")
        self.assertEqual(install_section(BASE_B).form, "fields")

    # ----------------------------------------------------------- form A

    def test_form_a(self):
        sec = install_section(BASE_A)
        self.assertEqual((sec.form, sec.asks_for, sec.writes, sec.steps, sec.context_files),
                         ("nothing", None, None, None, ()))
        self.assertFalse(sec.steps_instruction)
        self.assertEqual(sec.body, "## Install\n\nNothing to install.\n")

    def test_form_a_may_carry_a_note_over_wrapped_lines(self):
        sec = install_section(mutate(BASE_A, "Nothing to install.\n",
                                     "Nothing to install. An install may write an\noptional CONTEXT.md.\n"))
        self.assertEqual(sec.form, "nothing")

    def test_form_a_second_paragraph_is_refused(self):
        self.refused(mutate(BASE_A, "Nothing to install.\n", "Nothing to install.\n\nMore.\n"),
                     "form A", "one paragraph")

    def test_form_a_first_sentence_must_be_exact(self):
        for first in ("Nothing to install", "Nothing is installed.", "nothing to install.",
                      "Nothing to install, except the token.", "Nothing to install.Really."):
            with self.subTest(first):
                self.refused(mutate(BASE_A, "Nothing to install.\n", first + "\n"),
                             "neither form A", "Nothing to install.")

    # ----------------------------------------------------------- form B

    def test_form_b_fields(self):
        sec = install_section(BASE_B)
        self.assertEqual(sec.asks_for, "the bot token's path, and\nthe channel id.")
        self.assertEqual(sec.writes, "`config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`.")
        self.assertEqual(sec.steps, "`installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.")
        self.assertTrue(sec.steps_instruction)
        self.assertEqual(sec.body, BASE_B[BASE_B.index("## Install\n"):], "the body is verbatim to EOF")

    def test_steps_without_instruction(self):
        sec = install_section(mutate(BASE_B, "`installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.",
                                     "none beyond writing the files above."))
        self.assertFalse(sec.steps_instruction)

    def test_context_files_are_the_backticked_names_in_writes_in_order(self):
        self.assertEqual(install_section(BASE_B).context_files, ("config.json", "CONTEXT.md"))
        for writes, want in (
            ("`CONTEXT.md`, then `CONTEXT.md` again", ("CONTEXT.md",)),
            ("`config.example.json` copied", ()),
            ("CONTEXT.md and config.json, not backticked", ()),
            ("per agent, `<home>/CONTEXT.md` and `<home>/config.json`", ()),
            ("`config.json`", ("config.json",)),
        ):
            with self.subTest(writes):
                text = mutate(BASE_B, "`config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`.",
                              writes)
                self.assertEqual(install_section(text).context_files, want)

    def test_written_files_are_every_backticked_name_in_writes(self):
        self.assertEqual(install_section(BASE_B).written_files,
                         ("config.json", "CONTEXT.md", "<home>/config/zz.json"))
        self.assertEqual(install_section(BASE_A).written_files, ())
        text = mutate(BASE_B, "`config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`.",
                      "`a.json`, then `a.json` again, and `b\nsplit` over a line, then `c.json`.")
        self.assertEqual(install_section(text).written_files, ("a.json", "b split", "c.json"),
                         "a span may cross a line, as in Markdown, so the ticks after it still pair")

    def test_context_files_come_from_writes_only(self):
        text = mutate(BASE_B, "the channel id.", "the channel id, kept in `CONTEXT.md`.")
        text = mutate(text, "An optional paragraph after Steps.", "An optional `config.json`.")
        text = mutate(text, "`config.json` and `CONTEXT.md`, and per agent,", "per agent,")
        self.assertEqual(install_section(text).context_files, ())

    def test_form_b_missing_field(self):
        for field, para in (("Asks for", "**Asks for:** the bot token's path, and\nthe channel id.\n\n"),
                            ("Writes", "**Writes:** `config.json` and `CONTEXT.md`, and per agent,\n"
                                       "`<home>/config/zz.json`.\n\n"),
                            ("Steps", "**Steps:** `installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.\n\n")):
            with self.subTest(field):
                self.refused(mutate(BASE_B, para, ""), f"'**{field}:**' is missing")

    def test_form_b_empty_field(self):
        for field, value in (("Asks for", " the bot token's path, and\nthe channel id."),
                             ("Writes", " `config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`."),
                             ("Steps", " `installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.")):
            with self.subTest(field):
                self.refused(mutate(BASE_B, f"**{field}:**{value}", f"**{field}:**  "),
                             f"'**{field}:**'", "is empty")

    def test_form_b_repeated_field(self):
        for field in skills.FIELDS:
            with self.subTest(field):
                self.refused(mutate(BASE_B, "An optional paragraph after Steps.", f"**{field}:** again."),
                             f"'**{field}:**' is repeated")

    def test_form_b_out_of_order(self):
        asks = "**Asks for:** the bot token's path, and\nthe channel id.\n\n"
        writes = "**Writes:** `config.json` and `CONTEXT.md`, and per agent,\n`<home>/config/zz.json`.\n\n"
        self.refused(mutate(BASE_B, asks + writes, writes + asks), "out of order")

    def test_form_b_paragraph_before_or_between_fields(self):
        for anchor in ("**Asks for:**", "**Writes:**", "**Steps:**"):
            with self.subTest(anchor):
                self.refused(mutate(BASE_B, anchor, "A stray paragraph.\n\n" + anchor),
                             "first three paragraphs", "is not a field")

    def test_form_b_field_must_start_a_paragraph(self):
        self.refused(mutate(BASE_B, "the channel id.\n\n**Writes:**", "the channel id.\n**Writes:**"),
                     "'**Writes:**'", "does not start a paragraph")

    def test_neither_form(self):
        self.refused(mutate(BASE_A, "Nothing to install.\n", "Run the installer.\n"),
                     "neither form A", "nor form B")

    def test_empty_section(self):
        self.refused(mutate(BASE_A, "Nothing to install.\n", "\n\n"), "is empty")

    # ------------------------------------------------- headings and fences

    def test_no_heading(self):
        self.refused(mutate(BASE_A, "## Install\n", "## Installation\n"), "no '## Install' heading")
        self.refused(mutate(BASE_A, "## Install\n", "## 2. Install\n"), "no '## Install' heading")

    def test_two_headings(self):
        self.refused(mutate(BASE_A, "## 1. Rules\n", "## Install\n"), "2 '## Install' headings", "lines")

    def test_not_last(self):
        self.refused(BASE_A + "\n## 9. Later\n\nText.\n", "is not the last heading", "'## 9. Later'")

    def test_a_level_one_heading_after_it_is_refused_too(self):
        self.refused(BASE_A + "\n# Appendix\n", "is not the last heading", "'# Appendix'")

    def test_level_three_headings_are_not_counted(self):
        self.refused(mutate(BASE_A, "## Install\n", "### Install\n"), "no '## Install' heading")
        sec = install_section(BASE_B + "\n### A subsection\n\nText.\n")
        self.assertEqual(sec.form, "fields", "a ### after it is a subsection of it")
        self.assertTrue(sec.body.endswith("### A subsection\n\nText.\n"))

    def test_a_fenced_heading_does_not_count(self):
        for fence in ("```", "~~~", "```markdown"):
            with self.subTest(fence):
                close = fence[:3]
                only = mutate(BASE_A, "## Install\n\nNothing to install.\n",
                              f"{fence}\n## Install\n\nNothing to install.\n{close}\n")
                self.refused(only, "no '## Install' heading")
                example = mutate(BASE_A, "## 1. Rules\n", f"{fence}\n## Install\n\n## Other\n{close}\n\n## 1. Rules\n")
                self.assertEqual(install_section(example).form, "nothing")

    def test_a_fenced_heading_after_it_does_not_count(self):
        sec = install_section(BASE_B + "\n```markdown\n## Not a heading\n\n**Steps:** not a field\n```\n")
        self.assertEqual(sec.steps, "`installation/INSTRUCTION.md`; its steps 3 and 4 are per agent.")

    def test_a_fence_closes_only_on_its_own_kind(self):
        # A ```` fence holding ``` lines, and a ~~~ fence holding ``` lines: neither inner line closes it,
        # so the `## Install` inside stays fenced and the real one is the only one.
        for open_, inner, close in (("````", "```", "````"), ("~~~", "```", "~~~"), ("```", "```bash", "```")):
            with self.subTest(open_ + inner):
                text = mutate(BASE_A, "## 1. Rules\n",
                              f"{open_}\n{inner}\n## Install\n{close}\n\n## 1. Rules\n")
                self.assertEqual(install_section(text).form, "nothing")

    # ------------------------------------- CommonMark indentation (0 to 3 spaces)

    def test_a_heading_counts_with_up_to_three_leading_spaces(self):
        for lead in (" ", "  ", "   "):
            with self.subTest(lead=len(lead)):
                self.refused(BASE_A + f"\n{lead}## Later\n", "is not the last heading", "'## Later'")
                text = mutate(BASE_A, "## Install\n", f"{lead}## Install\n")
                self.assertEqual(install_section(text).form, "nothing")

    def test_four_spaces_or_a_tab_is_indented_code_not_a_heading(self):
        for lead in ("    ", "\t", " \t"):
            with self.subTest(lead=lead):
                self.assertEqual(install_section(BASE_B + f"\n{lead}## Later\n").form, "fields",
                                 "an indented-code block after Steps is part of the section, not a heading")
                self.refused(mutate(BASE_A, "## Install\n", f"{lead}## Install\n"), "no '## Install' heading")

    def test_a_fence_opens_only_with_up_to_three_spaces(self):
        for lead in (" ", "   "):
            with self.subTest(lead=len(lead)):
                text = mutate(BASE_A, "## 1. Rules\n", f"{lead}```\n## Install\n{lead}```\n\n## 1. Rules\n")
                self.assertEqual(install_section(text).form, "nothing", "the fenced heading does not count")
        for lead in ("    ", "\t"):
            with self.subTest(lead=lead):
                # Indented code, not a fence: the real heading below it is not swallowed by an
                # opener that never was one.
                text = mutate(BASE_A, "## 1. Rules\n", f"{lead}```\n{lead}x\n\n## 1. Rules\n")
                self.assertEqual(install_section(text).form, "nothing")

    def test_a_fence_closes_only_with_up_to_three_spaces(self):
        # The four-space ``` is the fence's content, so the `## Install` after it is still fenced.
        text = mutate(BASE_A, "## 1. Rules\n", "```\n    ```\n## Install\n```\n\n## 1. Rules\n")
        self.assertEqual(install_section(text).form, "nothing")
        text = mutate(BASE_A, "## 1. Rules\n", "```\nx\n   ```\n\n## 1. Rules\n")
        self.assertEqual(install_section(text).form, "nothing", "a three-space ``` closes it")

    def test_a_field_marker_counts_with_up_to_three_spaces(self):
        sec = install_section(mutate(BASE_B, "**Writes:**", "   **Writes:**"))
        self.assertEqual(sec.context_files, ("config.json", "CONTEXT.md"))

    def test_an_indented_code_marker_is_not_a_field(self):
        self.refused(mutate(BASE_B, "**Writes:**", "    **Writes:**"), "'**Writes:**' is missing")
        sec = install_section(mutate(BASE_B, "the channel id.\n", "the channel id.\n    **Steps:** quoted, not a field.\n"))
        self.assertIn("**Steps:** quoted", sec.asks_for, "a lazy continuation line, not a misplaced field")

    def test_indented_code_is_not_form_a(self):
        self.refused(mutate(BASE_A, "Nothing to install.\n", "    Nothing to install.\n"), "neither form A")

    def test_frontmatter_is_not_body(self):
        text = mutate(BASE_A, "requires_install: false\n", "requires_install: false\n## Install\n")
        self.assertEqual(install_section(text).form, "nothing")

    def test_crlf_text(self):
        sec = install_section(BASE_B.replace("\n", "\r\n"))
        self.assertEqual((sec.form, sec.context_files), ("fields", ("config.json", "CONTEXT.md")))
        self.assertTrue(sec.body.startswith("## Install\r\n"), "the body is verbatim, line endings kept")

    def test_error_is_a_fleet_error_with_the_drift_code(self):
        err = self.refused("# zz\n\nNo section.\n", "no '## Install' heading")
        self.assertIsInstance(err, FleetError)
        self.assertIsInstance(err, ValueError, "an `except ValueError` caller keeps catching it")
        self.assertEqual(err.exit_code, DRIFT)
        self.assertEqual(DRIFT, 1)
        self.assertEqual(str(err), err.message, "str() is the message, with nothing appended")

    def test_message_names_no_path(self):
        err = self.refused("# zz\n\nNo section.\n", "no '## Install' heading")
        self.assertNotIn("SKILL.md", str(err))
        self.assertIsInstance(err, ValueError)


if __name__ == "__main__":
    unittest.main()
