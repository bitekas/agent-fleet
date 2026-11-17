"""A skill's `## Install` section: the one reader of its format.

    sec = install_section(Path(".claude/skills/<skill>/SKILL.md").read_text())
    sec.form            # "nothing" (form A) or "fields" (form B)
    sec.context_files   # ("CONTEXT.md", "config.json") backticked in Writes

The format is claude-skill section 3 ("The `## Install` section"); this module
is its one home in code, shared by the install-section gate (tests/gates/) and
`fleet skills`. It reads TEXT only. Whether the skill's directory agrees with
the section (installation/INSTRUCTION.md, installation/check,
config.example.json, requires_install) is the gate's, which reads the tree and
calls this for the text.

Rules, each load-bearing:

  * Only a line OUTSIDE fenced code counts as a heading, and a fence closes
    only on the same character (``` or ~~~), at least as long, with nothing
    after it. claude-skill shows an example section inside a fence; a reader
    that counted it would see two `## Install` headings in that file, and one
    that closed a ```` fence on a ``` line would read the rest of the example
    as headings.
  * A leading `---` frontmatter block is not body: `## x` there is a YAML
    comment, never a heading.
  * `## Install` is the LAST level-1 or level-2 heading: the section runs to the
    end of the file, so `body` is exactly what `fleet skills --select` prints.
    A `#` or `##` heading after it would be printed as part of the install.
    `###` and deeper are subsections of it and allowed.
  * Paragraphs split on blank lines outside fences; a fenced block is part of
    the paragraph it sits in, and a field marker inside it is not a field.
  * Form A is recognised by its first sentence alone, `Nothing to install.`;
    anything else is read as form B and held to its three fields, so a section
    that is neither is refused rather than guessed.

Standard library only. InstallSectionError's message says what is wrong and
where (a line number of the text), never a path: the caller knows the path.
"""

import re
from dataclasses import dataclass

HEADING = "## Install"
NOTHING = "Nothing to install."
FIELDS = ("Asks for", "Writes", "Steps")
INSTRUCTION = "installation/INSTRUCTION.md"
CONTEXT_FILES = ("CONTEXT.md", "config.json")

_FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")
_TOP_HEADING = re.compile(r"#{1,2}(?:[ \t]|$)")
_MARKER = re.compile(r"\*\*(%s):\*\*" % "|".join(map(re.escape, FIELDS)))
_CONTEXT_FILE = re.compile(r"`(%s)`" % "|".join(map(re.escape, CONTEXT_FILES)))


class InstallSectionError(ValueError):
    """The text has no readable `## Install` section; the message says why."""


@dataclass(frozen=True)
class InstallSection:
    form: str                   # "nothing" (A) or "fields" (B)
    body: str                   # verbatim, from the "## Install" line to EOF
    asks_for: str | None        # each field's text after its marker (B); None for A
    writes: str | None
    steps: str | None
    context_files: tuple        # "CONTEXT.md" / "config.json" backticked in Writes (B); () for A

    @property
    def steps_instruction(self):
        """True when Steps names installation/INSTRUCTION.md (always False for A)."""
        return self.steps is not None and INSTRUCTION in self.steps


def _scan(lines, start):
    """(index, in_fence) for each line from `start`: in_fence is True for a fence
    line itself and every line between an opening and its closing fence."""
    fence = None
    for i in range(start, len(lines)):
        m = _FENCE.match(lines[i])
        if fence is None:
            if m and "`" not in (m.group(2) if m.group(1)[0] == "`" else ""):
                fence = m.group(1)
                yield i, True
                continue
            yield i, False
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = None
            yield i, True


def _body_start(lines):
    """The first line after a leading `---` frontmatter block (0 when there is none)."""
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                return i + 1
    return 0


def _paragraphs(lines, start):
    """[(first line index, [(line, in_fence), ...]), ...] from `start`, split on
    blank lines outside fences."""
    out, cur = [], None
    for i, fenced in _scan(lines, start):
        if not fenced and not lines[i].strip():
            cur = None
            continue
        if cur is None:
            cur = (i, [])
            out.append(cur)
        cur[1].append((lines[i], fenced))
    return out


def _text(para):
    return " ".join(line.strip() for line, _ in para[1])


def install_section(text):
    """The `## Install` section of a whole SKILL.md `text`, or InstallSectionError."""
    raw = text.splitlines(keepends=True)
    lines = [l.rstrip("\r\n") for l in raw]
    start = _body_start(lines)
    heads = [(i, lines[i]) for i, fenced in _scan(lines, start)
             if not fenced and _TOP_HEADING.match(lines[i])]
    installs = [i for i, h in heads if h.rstrip() == HEADING]
    if not installs:
        raise InstallSectionError(f"no '{HEADING}' heading outside fenced code")
    if len(installs) > 1:
        raise InstallSectionError(f"{len(installs)} '{HEADING}' headings (lines "
                                  f"{', '.join(str(i + 1) for i in installs)}); exactly one is allowed")
    at = installs[0]
    after = [(i, h) for i, h in heads if i > at]
    if after:
        i, h = after[0]
        raise InstallSectionError(f"the '{HEADING}' heading (line {at + 1}) is not the last heading: "
                                  f"'{h.strip()}' follows at line {i + 1}; the section runs to the end of the file")
    body = "".join(raw[at:])
    paras = _paragraphs(lines, at + 1)
    if not paras:
        raise InstallSectionError(f"the '{HEADING}' section (line {at + 1}) is empty")

    first = _text(paras[0])
    if first == NOTHING or first.startswith(NOTHING + " "):
        if len(paras) > 1:
            raise InstallSectionError(f"form A ('{NOTHING}') is one paragraph; a second one starts at "
                                      f"line {paras[1][0] + 1}")
        return InstallSection("nothing", body, None, None, None, ())

    # Form B: every marker that starts a line outside a fence, and where it sits.
    found = []  # (field, paragraph number, line index)
    for n, (first_line, plines) in enumerate(paras):
        for k, (line, fenced) in enumerate(plines):
            m = _MARKER.match(line.lstrip())
            if m and not fenced:
                if k:
                    raise InstallSectionError(f"'**{m.group(1)}:**' at line {first_line + k + 1} does not "
                                              f"start a paragraph; each field is its own paragraph, after a "
                                              f"blank line")
                found.append((m.group(1), n, first_line))
    names = [f for f, _, _ in found]
    if not names:
        raise InstallSectionError(f"the section is neither form A (its first sentence is not '{NOTHING}') "
                                  f"nor form B (it has none of the fields "
                                  f"{', '.join('**%s:**' % f for f in FIELDS)})")
    for f in FIELDS:
        if names.count(f) > 1:
            raise InstallSectionError(f"form B: '**{f}:**' is repeated")
        if f not in names:
            raise InstallSectionError(f"form B: '**{f}:**' is missing")
    if names != list(FIELDS) or [n for _, n, _ in found] != [0, 1, 2]:
        if names != list(FIELDS):
            raise InstallSectionError(f"form B: the fields are out of order ({', '.join(names)}); "
                                      f"they are {', '.join(FIELDS)}")
        stray = next(n for n in range(3) if n not in [p for _, p, _ in found])
        raise InstallSectionError(f"form B: the three fields are the section's first three paragraphs; "
                                  f"the paragraph at line {paras[stray][0] + 1} is not a field")
    values = []
    for f, n, line_at in found:
        plines = [line for line, _ in paras[n][1]]
        plines[0] = plines[0].lstrip()[len(f"**{f}:**"):]
        value = "\n".join(l.strip() for l in plines).strip()
        if not value:
            raise InstallSectionError(f"form B: '**{f}:**' (line {line_at + 1}) is empty")
        values.append(value)
    asks_for, writes, steps = values
    seen = []
    for name in _CONTEXT_FILE.findall(writes):
        if name not in seen:
            seen.append(name)
    return InstallSection("fields", body, asks_for, writes, steps, tuple(seen))


__all__ = ["InstallSection", "InstallSectionError", "install_section",
           "HEADING", "NOTHING", "FIELDS", "INSTRUCTION", "CONTEXT_FILES"]
