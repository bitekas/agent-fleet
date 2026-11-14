#!/usr/bin/env python3
"""Check feature checklists before a build goes to a tester.

    check_checklist.py <checklist.md | directory> ... [--expect SLUG[,SLUG...]]...
                       [--served WORKTREE] [--config PATH]

A feature checklist is one Markdown file per feature, made from
feature-checklist.template.md beside this script; SKILL.md's "The feature
checklist" says when it is made, who fills each section, and who runs this.
The template's own comments document the format. This header is the contract
of the script.

ARGUMENTS
    <checklist.md>   one checklist. Its file name is <slug>.md and its header's
                     Slug row must say the same.
    <directory>      every *.md file directly inside it is a checklist.
    --expect SLUG    the features that MUST have a checklist (repeatable, or
                     comma-separated). With it, a directory argument is a place
                     to LOOK: only <SLUG>.md files are taken from it, and an
                     expected slug with no file is a finding (MISSING), never a
                     skip. A file named explicitly is checked either way. This
                     is how a release candidate checks exactly the features in
                     its changelist, not every checklist that ever landed.
    --served WORKTREE
                     the worktree the build is SERVED from, to a tester. Every
                     normal check runs, plus three, so the build the tester gets
                     is the build the evidence is for:
                     (1) every checklist has a filled section 6 hand-off row;
                     (2) the worktree's HEAD contains every checklist's section
                         6 hand-off commit (merge-base --is-ancestor) - a serve
                         from an older commit is a finding naming both shas;
                     (3) with exactly ONE checklist, every file changed between
                         its hand-off commit and the served HEAD is under
                         checklist.dir: writing the section 6 row is itself a
                         commit after the checked one, and anything else is
                         code the checker never saw.
                     THE STATED LIMIT: with several checklists (a release
                     candidate's serve) only (2) applies, because the RC branch
                     legitimately carries other features' commits. On a pass it
                     prints the line the hand-off message carries:
                     `SERVED <path> at <sha>: contains the hand-off commit(s)
                     <shas>`, plus `; nothing but checklists changed since`
                     when (3) applied. A path that is not a git worktree, or
                     whose HEAD does not resolve, is NO VERDICT. It reads git
                     and nothing else: the build being served is identified by
                     its worktree's HEAD, not by any dev-server log.
    --config PATH    the config to read instead of the install's. Default: this
                     skill's config.json in the install context, resolved
                     through fleetlib (`fleet where definition-of-done
                     config.json`); the tests pass their own. Read from it:
                     checklist.waivers, the allow-list of people who may waive;
                     checklist.permalink_pattern, what a chat message permalink
                     looks like on the install's chat transport; and
                     checklist.dir (repo-relative), which --served needs; and
                     figma.file_key, whose null means the project has no design
                     file (see NO DESIGN FILE below). Each is a value of the
                     install, so it lives there and not here.

EXIT CODES - three, never collapsed. Several files: the worst of them wins
(2 over 1 over 0), and each file still gets its own verdict line.

    0  PASS. Every file passed, and the run checked at least one.
    1  FINDINGS. At least one file has findings, each printed as
       `<file>:<line>: <what is wrong>`, or an --expect slug has no file.
       Every 1 ends with a `FINDINGS` or `MISSING` line on stdout.
    2  NO VERDICT. A file is malformed (a section or table missing - except
       section 4b, whose absence is a finding - a column renamed, a row with
       the wrong cell count), unreadable, outside a git
       checkout; or the run itself could not start (usage, a config that
       does not resolve or lacks a required key, SKILL.md's rule table
       unreadable, a --served path that is not a worktree with a HEAD); or it
       checked nothing.

A 2 IS NOT A PASS. Nothing was judged, so nothing was found; a caller that
reads "no findings printed" as clean has passed a file nobody read. That is
also why EVERY unexpected exception is mapped to 2: Python's own status for an
uncaught exception is 1, this script's "findings", and a crash must not
masquerade as a judgement in either direction. An exit 1 with no FINDINGS or
MISSING line is therefore a fault (the interpreter could not run this file at
all - a SyntaxError in a mid-merge copy), handled like 2.

Per-file verdict lines and findings go to stdout; a run-level NO VERDICT (bad
usage, bad config) goes to stderr.

NO DESIGN FILE. With figma.file_key null the project has no design file, so
sections 1a, 1b, 1c and 4 have nothing to hold: their tables must still be
there, every row in them is still checked, but empty tables are accepted where
otherwise 1a must have rows and, while the header names screens, 1b or 1c and
4 must too. The run prints one `NOTE` line on stdout saying so. A config that
carries no figma.file_key key at all is NO VERDICT: an absent key must never
relax a gate, so a project without a design file says so with null.

WHAT IT REFUSES (exit 1), each per row and each with the row's line:
    - an empty cell: every cell of every row is owed, so an empty item is a
      finding, not a blank;
    - a status outside its section's closed vocabulary, including a qualified
      one ("PASS (header only)" is not PASS);
    - TODO anywhere; INCONCLUSIVE or FAIL in section 4;
    - WAIVED by a name that is not on the allow-list;
    - evidence that is not a path or a URL where one is owed, and a local path
      that cannot be opened. A path is resolved against the repository root
      (absolute and ~/ paths as written); a Markdown link's relative target is
      resolved against the checklist's own directory, as Markdown renders it.
      A URL is accepted as it stands: this script makes no network call;
    - a commit that does not resolve in this clone;
    - a rule number from SKILL.md's rule table with no row in section 5, or a
      row naming a rule that table does not have. The numbers are READ from
      that table, so appending a rule there reds every checklist that lacks
      its row - the enumeration has one source;
    - uncommitted changes to the checklist: the record names a commit, so the
      file checked must be that commit's;
    - section 5's `6 - presented to the requester` row (PRESENTED_ROW, the one
      row read by its label and not only its rule number) missing; DONE with
      no chat message permalink in its evidence (a link that full-matches
      checklist.permalink_pattern); N/A while the header's Screens is not
      `none`; or AFTER HAND-OFF, because it comes before the hand-off;
    - the RUNNER being the BUILDER named in the header (case-insensitive);
    - section 4b, the bug hunt by an agent that did not build the feature:
      the section missing; a run table that does not hold exactly one row; a
      hunter who is the builder (the same comparison as the runner's); a
      build commit, or a `FIXED in <commit>`, that is not a resolvable sha
      equal to or an ancestor of the hand-off commit (the commit section 6
      records, else the commit being checked); a scope given that does not
      point at section 2; a Run at that is not ISO 8601 UTC; an empty
      findings table (a hunt that found nothing has one row, Finding NONE and
      Disposition `-`, alone in its table); a disposition that is not
      `FIXED in <commit>`, `WAIVED by <name>` or `NOT A BUG: <reason>` with a
      reason. Waivers, evidence, empty cells and TODO go through the same
      checks as every other section.

THE RUNNER is the name in the author identity git would commit with in the
checklist's clone (`git var GIT_AUTHOR_IDENT`): the agent's service unit
supplies it to every repo the session touches, and the clone's user.name is the
fallback. THIS IS EVIDENCE, NOT AUTHENTICATION. Anyone can set an identity.
The check makes self-certification a deliberate, visible act instead of the
default, and the record in section 6 names who ran it on which commit; it does
not and cannot prove who did.

On a PASS it prints the row to record in the file's section 6
(`| <runner> | <commit> | <ISO UTC> |`). A filled section 6 row is checked too:
its runner must not be the builder and its commit must resolve.

Stdlib only, plus the fleet's own fleetlib for the default config; it reads
files and runs git, and writes nothing.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

# realpath, never abspath: run through an agent's skill link, the unresolved
# path is the link directory, which holds neither SKILL.md (the rule table) nor
# a fleet tree three levels up (fleetlib, which resolves the install's config).
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SKILL_MD = os.path.join(HERE, "SKILL.md")
SKILL = "definition-of-done"


class NoVerdict(Exception):
    """This file (or this run) cannot be judged: exit 2."""


# -- the format --
# Section key -> its tables, in order, each a list of lowercased column names.
# Every section holds one table except 4b, which holds the run and its findings.
# The template's comments document the same format for the person filling it
# in; a change here is a change there.
COLUMNS = {
    "header": [["field", "value"]],
    "1a": [["item", "status", "evidence"]],
    "1b": [["frame", "plan item", "status", "evidence"]],
    "1c": [["screen", "asked", "status", "evidence"]],
    "2": [["scope item", "status", "evidence"]],
    "3": [["date", "who", "ruling", "frame and note", "commit", "status", "evidence"]],
    "4": [["screen and state", "frame", "verdict", "evidence"]],
    "4b": [["hunter", "build (commit)", "scope given", "run at (utc)", "evidence"],
           ["#", "finding", "disposition", "evidence"]],
    "5": [["rule", "status", "evidence"]],
    "6": [["checker run by", "commit", "at (utc)"]],
}
SECTION_ORDER = list(COLUMNS)
# A section whose ABSENCE is unfinished work rather than a malformed file: 4b
# joined the template after checklists already existed, and a checklist without
# it owes a hunt, which is a finding (exit 1), not a NO VERDICT (exit 2).
FINDING_IF_MISSING = {"4b"}
HEADER_FIELDS = ["feature", "slug", "builder", "requester", "screens", "started"]

# Status column per section and its closed vocabulary. Values that need
# evidence (a path or URL) vs values that need a non-empty reason only.
STATUS_COLUMN = {"1a": "status", "1b": "status", "1c": "status", "2": "status",
                 "3": "status", "4": "verdict", "5": "status"}
NEEDS_REFERENCE = {
    "1a": {"DONE"}, "1b": {"DONE"}, "1c": {"NO DESIGN"}, "2": {"DONE"},
    "3": {"RE-FROZEN"}, "4": {"PASS", "NO DESIGN", "AHEAD", "WAIVED"},
    "4b": {"FIXED", "WAIVED", "NOT A BUG"}, "5": {"DONE"},
}
REASON_ONLY = {"5": {"N/A", "AFTER HAND-OFF"}}
# Statuses that carry an argument, as the vocabulary shows them.
PARAMETERIZED = {"WAIVED": "WAIVED by <name>", "FIXED": "FIXED in <commit>",
                 "NOT A BUG": "NOT A BUG: <reason>"}
WAIVED_RE = re.compile(r"^WAIVED by\s+(.+)$")
FIXED_RE = re.compile(r"^FIXED in\s+(\S+)$")
NOT_A_BUG_RE = re.compile(r"^NOT A BUG:(.*)$")
SCOPE_RE = re.compile(r"(?:\u00a7|section)\s*2\b", re.IGNORECASE)
# The section-5 row read by its label: Rule 6's presentation to the requester.
# The template carries it written exactly so; its evidence is a chat message,
# whose permalink full-matches the config's checklist.permalink_pattern.
PRESENTED_ROW = "6 - presented to the requester"

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
URL = re.compile(r"^https?://\S+$")
URL_IN = re.compile(r"https?://\S+")
LINK = re.compile(r"\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
CODE = re.compile(r"`([^`]+)`")
EXT = re.compile(r"\.[A-Za-z0-9]+(?::\d+(?:-\d+)?)?$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SECTION_KEY = re.compile(r"^(\d+[a-z]?)[.)]?(?:\s|$)")
RULE_CELL = re.compile(r"^(?:rule\s+)?(\d+)\b", re.IGNORECASE)
RULE_TABLE_ROW = re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|")


# -- small helpers --

def git(cwd, *args):
    """(returncode, stdout stripped). Never raises on a git failure."""
    try:
        p = subprocess.run(["git", "-C", cwd] + list(args),
                           capture_output=True, text=True)
    except OSError as e:
        return 127, str(e)
    return p.returncode, p.stdout.strip()


def strip_comments(text):
    """Blank out HTML comments, keeping every newline so line numbers hold."""
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.DOTALL)


def split_row(line):
    """Cells of one Markdown table row; `\\|` is a literal pipe."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [c.replace("\\|", "|").strip() for c in cells]


def norm_col(c):
    return re.sub(r"\s+", " ", c.replace("*", "").strip().lower())


def looks_like_ref(s, strict):
    """Is this token a path or a URL? `strict` for bare (unquoted) tokens."""
    if URL.match(s):
        return True
    if strict:
        if "/" not in s:
            return False
        return (s.startswith(("/", "./", "../", "~/")) or s.endswith("/")
                or bool(EXT.search(s)))
    return "/" in s or bool(EXT.search(s))


def references(cell):
    """Every path or URL a cell points at, as (kind, target).

    kind is "link" for a Markdown link target (relative to the checklist's
    directory) and "ref" for everything else (relative to the repo root)."""
    refs = [("link", m.group(2)) for m in LINK.finditer(cell)]
    rest = LINK.sub(" ", cell)
    for m in CODE.finditer(rest):
        s = m.group(1).strip()
        if s and not re.search(r"\s", s) and looks_like_ref(s, strict=False):
            refs.append(("ref", s))
    rest = CODE.sub(" ", rest)
    for tok in re.split(r"[\s,;]+", rest):
        tok = tok.strip("()[]<>\"'").rstrip(".")
        if tok and looks_like_ref(tok, strict=True):
            refs.append(("ref", tok))
    return refs


def open_problem(path):
    """None when the path can be opened the way a reviewer opens it; else why.

    It OPENS the file (or lists the directory) rather than asking whether it
    exists: a path that exists and cannot be read is not evidence anyone can
    look at."""
    try:
        if os.path.isdir(path):
            os.listdir(path)
        else:
            with open(path, "rb") as f:
                f.read(1)
        return None
    except OSError as e:
        return e.strerror or str(e)


# -- one file --

class Checklist(object):
    def __init__(self, path, waivers, rules, permalink, design=True):
        self.path = path
        self.waivers = waivers
        self.rules = rules
        self.permalink = permalink
        self.design = design
        self.findings = []
        self.dir = os.path.dirname(os.path.abspath(path))
        self.root = None
        self.runner = None
        self.builder = ""
        self.head = None
        self.handoff = None
        self.handoff_heading = 1

    def find(self, line, msg):
        self.findings.append((line, msg))

    # The file -> {section key: (heading line, [table, ...])}, each table a list
    # of (line, {column: cell}); a FINDING_IF_MISSING section may be absent.
    def parse(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise NoVerdict("unreadable: %s" % e)
        lines = strip_comments(text).split("\n")
        sections = {}
        key = None
        for i, line in enumerate(lines, 1):
            m = HEADING.match(line)
            if m:
                title = m.group(2)
                k = SECTION_KEY.match(title)
                if title.lower().startswith("header"):
                    key = "header"
                elif k:
                    key = k.group(1)
                else:
                    key = None
                if key in COLUMNS:
                    if key in sections:
                        raise NoVerdict("section %s appears twice (line %d)" % (key, i))
                    sections[key] = {"line": i, "tables": [], "cur": None}
                else:
                    key = None
                continue
            if key is None:
                continue
            sec = sections[key]
            if line.lstrip().startswith("|"):
                if sec["cur"] is None:
                    sec["cur"] = []
                    sec["tables"].append(sec["cur"])
                sec["cur"].append((i, line))
            else:
                sec["cur"] = None
        missing = [k for k in SECTION_ORDER
                   if k not in sections and k not in FINDING_IF_MISSING]
        if missing:
            raise NoVerdict("missing section(s): %s" % ", ".join(
                "Header" if k == "header" else k for k in missing))
        out = {}
        for k in SECTION_ORDER:
            if k not in sections:
                continue
            sec = sections[k]
            if len(sec["tables"]) != len(COLUMNS[k]):
                raise NoVerdict("section %s (line %d) holds %d tables, expected %d"
                                % (k, sec["line"], len(sec["tables"]), len(COLUMNS[k])))
            tables = []
            for table, want in zip(sec["tables"], COLUMNS[k]):
                if len(table) < 2:
                    raise NoVerdict("section %s's table (line %d) has no header separator"
                                    % (k, table[0][0]))
                cols = [norm_col(c) for c in split_row(table[0][1])]
                if cols != want:
                    raise NoVerdict("section %s's table (line %d) has columns %s, expected %s"
                                    % (k, table[0][0], cols, want))
                sep = split_row(table[1][1])
                if len(sep) != len(cols) or not all(re.match(r"^:?-+:?$", c) for c in sep):
                    raise NoVerdict("section %s's table (line %d) has no valid separator row"
                                    % (k, table[1][0]))
                rows = []
                for ln, raw in table[2:]:
                    cells = split_row(raw)
                    if len(cells) != len(cols):
                        raise NoVerdict("line %d has %d cells, its table has %d"
                                        % (ln, len(cells), len(cols)))
                    rows.append((ln, dict(zip(cols, cells))))
                tables.append(rows)
            out[k] = (sec["line"], tables)
        return out

    # -- evidence --
    def resolve(self, kind, target):
        t = target.split("#", 1)[0] if not URL.match(target) else target
        t = re.sub(r":\d+(?:-\d+)?$", "", t)
        t = os.path.expanduser(t)
        if os.path.isabs(t):
            return t
        base = self.dir if kind == "link" else self.root
        return os.path.normpath(os.path.join(base, t))

    def check_refs(self, ln, column, cell, required):
        """Validate every reference in a cell; require one when `required`."""
        refs = references(cell)
        if required and not refs and cell.strip():
            self.find(ln, "%s has no evidence a reviewer can open: give a path or a URL"
                      % column)
        for kind, target in refs:
            if URL.match(target):
                continue
            problem = open_problem(self.resolve(kind, target))
            if problem:
                self.find(ln, "%s path `%s` cannot be opened: %s" % (column, target, problem))

    def check_commit(self, ln, column, cell, allow_url=True):
        """The full sha a commit cell resolves to, or None (with a finding when
        it is wrong). A URL is accepted as it stands where `allow_url`, and
        then there is no sha to return."""
        c = cell.strip().strip("`").strip()
        if allow_url and URL.match(c):
            return None
        if not SHA.match(c):
            self.find(ln, "%s `%s` is %s" % (column, cell, "neither a commit sha nor a URL"
                                             if allow_url else "not a commit sha"))
            return None
        rc, full = git(self.root, "rev-parse", "--verify", "-q", c + "^{commit}")
        if rc != 0:
            self.find(ln, "%s %s does not resolve to a commit in this clone" % (column, c))
            return None
        return full

    def check_ancestor(self, ln, column, sha, handoff):
        """`sha` must be the hand-off commit or an ancestor of it."""
        if handoff and git(self.root, "merge-base", "--is-ancestor", sha, handoff)[0] != 0:
            self.find(ln, "%s %s is neither the hand-off commit %s nor an ancestor of it"
                      % (column, sha[:12], handoff[:12]))

    def recorded_handoff(self, rows6):
        """(line, full sha) of the hand-off commit section 6 records, or None."""
        for ln, cells in rows6:
            c = cells["commit"].strip().strip("`").strip()
            if SHA.match(c):
                rc, full = git(self.root, "rev-parse", "--verify", "-q", c + "^{commit}")
                if rc == 0:
                    return ln, full
        return None

    def check_served(self, served, single, checklist_dir):
        """--served: the build being served is the build the evidence is for."""
        if not self.handoff:
            self.find(self.handoff_heading, "--served: section 6 records no hand-off "
                      "commit, and a build served with no recorded hand-off is a build "
                      "no evidence is for")
            return
        ln, sha = self.handoff
        path, head = served
        if git(path, "merge-base", "--is-ancestor", sha, head)[0] != 0:
            self.find(ln, "--served: %s is at %s, which does not contain the hand-off "
                      "commit %s: it is serving a build the evidence is not for"
                      % (path, head[:12], sha[:12]))
            return
        if not single:
            return
        rc, out = git(path, "diff", "--name-only", sha, head)
        if rc != 0:
            raise NoVerdict("--served: git diff %s %s failed in %s" % (sha[:12], head[:12], path))
        prefix = checklist_dir.strip("/") + "/"
        code = [f for f in out.split("\n") if f and not f.startswith(prefix)]
        if code:
            shown = ", ".join(code[:20]) + (" and %d more" % (len(code) - 20) if len(code) > 20 else "")
            self.find(ln, "--served: %d file(s) outside %s changed between the hand-off "
                      "commit %s and the served %s, so the checker did not see the code "
                      "being served: %s" % (len(code), prefix, sha[:12], head[:12], shown))

    def is_builder(self, name):
        """The ONE comparison with the header's builder: trimmed, case-insensitive."""
        return bool(self.builder) and name.strip().lower() == self.builder.lower()

    def check_cells(self, ln, key, columns, cells):
        """Report an empty row or empty cells; False for an all-empty row."""
        if not any(v.strip() for v in cells.values()):
            self.find(ln, "empty row in %s: fill it or delete it" % key)
            return False
        for col in columns:
            if not cells[col].strip():
                self.find(ln, "empty %s" % col.capitalize())
        return True

    def check_waiver(self, ln, name):
        if name.lower() in [w.lower() for w in self.waivers]:
            return True
        self.find(ln, "waived by `%s`, who is not on the waiver allow-list (%s)"
                  % (name, ", ".join(self.waivers)))
        return False

    # -- the checks --
    def check(self):
        sections = self.parse()

        rc, root = git(self.dir, "rev-parse", "--show-toplevel")
        if rc != 0 or not root:
            raise NoVerdict("not inside a git checkout: repo-relative evidence and "
                            "the runner cannot be resolved")
        self.root = root
        rc, ident = git(self.dir, "var", "GIT_AUTHOR_IDENT")
        m = re.match(r"^(.*?)\s*<", ident) if rc == 0 else None
        if not m or not m.group(1).strip():
            raise NoVerdict("cannot establish who is running the checker "
                            "(`git var GIT_AUTHOR_IDENT` failed in this clone)")
        self.runner = m.group(1).strip()
        rc, head = git(self.root, "rev-parse", "HEAD")
        self.head = head if rc == 0 else None

        header = self.check_header(sections["header"])
        self.builder = header.get("builder", "").strip()
        no_screens = header.get("screens", "").strip().lower() in ("none", "-")

        def rows(k):
            return sections[k][1][0]

        for key in ["1a", "1b", "1c", "2", "3", "4", "5"]:
            self.check_rows(key, rows(key))

        if self.design and not rows("1a"):
            self.find(sections["1a"][0], "1a has no rows: the design read is owed before any code")
        if self.design and not no_screens:
            if not rows("1b") and not rows("1c"):
                self.find(sections["1b"][0], "no frames in 1b and no screens in 1c, "
                          "while the header names screens")
            if not rows("4"):
                self.find(sections["4"][0], "4 has no rows, while the header names "
                          "screens: every screen and state on the step sheet gets a verdict")
        if not rows("2"):
            self.find(sections["2"][0], "2 has no rows: a feature has at least one scope item")
        self.check_rule_coverage(sections["5"][0], rows("5"))
        self.check_presented(sections["5"][0], rows("5"), no_screens)
        self.check_handoff(rows("6"))
        self.handoff = self.recorded_handoff(rows("6"))
        self.handoff_heading = sections["6"][0]
        handoff = self.handoff[1] if self.handoff else self.head
        if "4b" in sections:
            self.check_hunt(sections["4b"], handoff)
        else:
            self.find(sections["4"][0], "no section 4b: the bug hunt by an agent that did "
                      "not build the feature is owed before the hand-off")

        if self.is_builder(self.runner):
            self.find(header.get("_builder_line", sections["header"][0]),
                      "the runner (%s) is the builder: an agent that did not build "
                      "the feature runs this check" % self.runner)
        rc, dirty = git(self.root, "status", "--porcelain", "--", os.path.abspath(self.path))
        if rc != 0 or dirty:
            self.find(1, "the checklist has uncommitted changes: commit it and re-run, "
                      "so the commit recorded in 6 is the file that was checked")

    def check_header(self, section):
        hline, (rows,) = section
        fields = {}
        for ln, cells in rows:
            name = norm_col(cells["field"])
            fields[name] = cells["value"]
            fields["_%s_line" % name] = ln
        for f in HEADER_FIELDS:
            if f not in fields:
                self.find(hline, "header has no %s row" % f.capitalize())
            elif not fields[f].strip():
                self.find(fields["_%s_line" % f], "empty header field %s" % f.capitalize())
        slug = fields.get("slug", "").strip().strip("`")
        stem = os.path.splitext(os.path.basename(self.path))[0]
        if slug and slug != stem:
            self.find(fields["_slug_line"], "slug `%s` does not match the file name "
                      "`%s.md`" % (slug, stem))
        started = fields.get("started", "").strip()
        if started and not ISO_DATE.match(started):
            self.find(fields["_started_line"], "Started `%s` is not an ISO date "
                      "(YYYY-MM-DD)" % started)
        return fields

    def check_rows(self, key, rows):
        status_col = STATUS_COLUMN[key]
        for ln, cells in rows:
            if not self.check_cells(ln, key, COLUMNS[key][0], cells):
                continue
            status = cells[status_col].strip()
            word = self.check_status(ln, key, status_col, status)
            evidence = cells["evidence"]
            if word in NEEDS_REFERENCE.get(key, ()):
                self.check_refs(ln, "Evidence", evidence, required=True)
            elif word in REASON_ONLY.get(key, ()):
                self.check_refs(ln, "Evidence", evidence, required=False)
            if key == "1b" and cells["frame"].strip() and not URL_IN.search(cells["frame"]):
                self.find(ln, "Frame needs the frame's name as a link to the design file")
            if (key == "4" and word == "PASS" and cells["frame"].strip()
                    and not URL_IN.search(cells["frame"])):
                self.find(ln, "PASS needs the frame it was checked against, as a link")
            if key == "3":
                if cells["date"].strip() and not ISO_DATE.match(cells["date"].strip()):
                    self.find(ln, "Date `%s` is not an ISO date" % cells["date"].strip())
                for col in ("ruling", "frame and note"):
                    if cells[col].strip():
                        self.check_refs(ln, col.capitalize(), cells[col], required=True)
                if cells["commit"].strip():
                    self.check_commit(ln, "Commit", cells["commit"])
            if key == "5":
                self.check_rule_cell(ln, cells["rule"])

    def check_status(self, ln, key, column, status):
        """Report a status outside the vocabulary; return the accepted word."""
        col = column.capitalize()
        if not status:
            return None
        if status == "TODO":
            self.find(ln, "TODO: not done")
            return None
        if key == "4":
            if status.upper().startswith("INCONCLUSIVE"):
                self.find(ln, "%s `%s`: INCONCLUSIVE is not a pass - fix the check and "
                          "re-run it, or record `WAIVED by <name>` (one of: %s) with a "
                          "link to the waiver" % (col, status, ", ".join(self.waivers)))
                return None
            if status.upper().startswith("FAIL"):
                self.find(ln, "%s `%s`: fix the screen and re-run the check" % (col, status))
                return None
        allowed = sorted(NEEDS_REFERENCE.get(key, set()) | REASON_ONLY.get(key, set()))
        if "WAIVED" in allowed:
            m = WAIVED_RE.match(status)
            if m:
                return "WAIVED" if self.check_waiver(ln, m.group(1).strip()) else None
        if "FIXED" in allowed and FIXED_RE.match(status):
            return "FIXED"
        if "NOT A BUG" in allowed:
            m = NOT_A_BUG_RE.match(status)
            if m:
                if m.group(1).strip():
                    return "NOT A BUG"
                self.find(ln, "%s `%s` gives no reason: NOT A BUG needs one after the colon"
                          % (col, status))
                return None
        if status in allowed and status not in PARAMETERIZED:
            return status
        shown = [PARAMETERIZED.get(a, a) for a in allowed]
        qualified = [a for a in allowed if a not in PARAMETERIZED and status.upper().startswith(a)]
        if qualified:
            self.find(ln, "%s `%s` qualifies %s, and a qualified %s is not %s: what was "
                      "not covered goes in a row of its own" % (col, status, qualified[0],
                                                                 qualified[0], qualified[0]))
        else:
            self.find(ln, "%s `%s` is not one of: %s" % (col, status, ", ".join(shown + ["TODO"])))
        return None

    def check_rule_cell(self, ln, cell):
        m = RULE_CELL.match(cell.strip())
        if not m:
            self.find(ln, "Rule `%s` does not start with a rule number" % cell)
        elif int(m.group(1)) not in self.rules:
            self.find(ln, "rule %s is not in the definition of done's rule table (%s)"
                      % (m.group(1), ", ".join(str(r) for r in self.rules)))

    def check_rule_coverage(self, hline, rows):
        seen = set()
        for _, cells in rows:
            m = RULE_CELL.match(cells["rule"].strip())
            if m:
                seen.add(int(m.group(1)))
        for r in self.rules:
            if r not in seen:
                self.find(hline, "rule %d has no row in 5" % r)

    def check_presented(self, hline, rows, no_screens):
        """The PRESENTED_ROW: DONE with the chat message's permalink, or N/A
        for a feature with no screens. TODO and words outside the vocabulary
        are check_status's; this adds what only this row refuses."""
        found = [(ln, c) for ln, c in rows if norm_col(c["rule"]) == PRESENTED_ROW]
        if not found:
            self.find(hline, "5 has no `%s` row: before the hand-off the builder shows the "
                      "requester, in the feature's chat thread, a video of the feature per "
                      "platform%s (N/A only when the header's Screens is none)"
                      % (PRESENTED_ROW, " and the design pixel-comparison pack with its diff "
                         "maps" if self.design else ""))
        for ln, cells in found:
            status, evidence = cells["status"].strip(), cells["evidence"]
            if (status == "DONE" and evidence.strip() and not any(
                    self.permalink.fullmatch(t) for _, t in references(evidence))):
                self.find(ln, "Evidence for `%s` is not a chat message permalink (a link "
                          "matching checklist.permalink_pattern `%s`): link the message that "
                          "showed the requester the videos and the diff maps"
                          % (PRESENTED_ROW, self.permalink.pattern))
            elif status == "N/A" and not no_screens:
                self.find(ln, "`%s` is N/A while the header names screens: N/A is only "
                          "for a feature whose Screens is none" % PRESENTED_ROW)
            elif status == "AFTER HAND-OFF":
                self.find(ln, "`%s` is AFTER HAND-OFF: the presentation comes before the "
                          "hand-off, so it is DONE before the checker passes" % PRESENTED_ROW)

    def check_handoff(self, rows):
        for ln, cells in rows:
            if not any(v.strip() for v in cells.values()):
                continue
            by, commit, at = (cells["checker run by"].strip(), cells["commit"],
                              cells["at (utc)"].strip())
            self.check_cells(ln, "6", COLUMNS["6"][0], cells)
            if by and self.is_builder(by):
                self.find(ln, "6 records the builder (%s) as the checker's runner" % by)
            if commit.strip():
                self.check_commit(ln, "Commit", commit)
            if at and not ISO_UTC.match(at):
                self.find(ln, "At `%s` is not ISO 8601 UTC (2026-10-09T00:29Z)" % at)

    def check_hunt(self, section, handoff):
        """Section 4b: one hunt, by a non-builder, on a build the hand-off
        contains, and every finding disposed of."""
        hline, (runs, finds) = section
        run_cols, find_cols = COLUMNS["4b"]
        if not runs:
            self.find(hline, "4b's run table is empty: no hunt is recorded, and one is "
                      "owed before the hand-off")
        elif len(runs) > 1:
            self.find(hline, "4b's run table holds %d rows: it records exactly one hunt, "
                      "on the build being handed off" % len(runs))
        for ln, cells in runs:
            if not self.check_cells(ln, "4b", run_cols, cells):
                continue
            hunter = cells["hunter"]
            if hunter.strip() and self.is_builder(hunter):
                self.find(ln, "the hunter (%s) is the builder: an agent that did not build "
                          "the feature hunts it" % hunter.strip())
            if cells["build (commit)"].strip():
                sha = self.check_commit(ln, "Build (commit)", cells["build (commit)"],
                                        allow_url=False)
                if sha:
                    self.check_ancestor(ln, "Build (commit)", sha, handoff)
            scope = cells["scope given"]
            if scope.strip() and not SCOPE_RE.search(scope):
                self.find(ln, "Scope given `%s` does not point at section 2: the hunter "
                          "gets the agreed scope and the build, nothing else" % scope.strip())
            at = cells["run at (utc)"].strip()
            if at and not ISO_UTC.match(at):
                self.find(ln, "Run at `%s` is not ISO 8601 UTC (2026-10-09T00:29Z)" % at)
            self.check_refs(ln, "Evidence", cells["evidence"], required=True)
        if not finds:
            self.find(hline, "4b's findings table is empty: a hunt that found nothing has "
                      "one row reading NONE, because an empty table reads exactly like a "
                      "hunt that was never run")
        if len(finds) > 1:
            for ln, cells in finds:
                if cells["finding"].strip().upper() == "NONE":
                    self.find(ln, "a NONE row is the only row: a hunt that found something "
                              "lists what it found")
        for ln, cells in finds:
            if not self.check_cells(ln, "4b", find_cols, cells):
                continue
            disposition = cells["disposition"].strip()
            if cells["finding"].strip().upper() == "NONE":
                if disposition and disposition != "-":
                    self.find(ln, "a NONE row's Disposition is `-`: there is nothing to "
                              "dispose of")
                self.check_refs(ln, "Evidence", cells["evidence"], required=True)
                continue
            word = self.check_status(ln, "4b", "disposition", disposition)
            if word:
                self.check_refs(ln, "Evidence", cells["evidence"], required=True)
            if word == "FIXED":
                sha = self.check_commit(ln, "FIXED in", FIXED_RE.match(disposition).group(1),
                                        allow_url=False)
                if sha:
                    self.check_ancestor(ln, "FIXED in", sha, handoff)


# -- the run --

def default_config():
    """This skill's config.json in the install context, resolved through
    fleetlib from the fleet tree this script really lives in. Only a run with
    no --config reaches it, so a caller passing a config needs no install."""
    sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
    try:
        from fleetlib import paths
        return str(paths.skill_context(SKILL) / "config.json")
    except Exception as e:  # noqa: BLE001 - any resolution failure is NO VERDICT
        raise NoVerdict("cannot resolve the install's config.json for %s (%s: %s); "
                        "pass --config, or set FLEET_CONTEXT_ROOT to the install root"
                        % (SKILL, type(e).__name__, e))


def load_config(path):
    """(waivers, checklist directory or None, permalink regex, design file?)
    from the config."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise NoVerdict("config %s unreadable: %s" % (path, e))
    block = (cfg.get("checklist") or {}) if isinstance(cfg, dict) else {}
    if not isinstance(block, dict):
        block = {}
    waivers = block.get("waivers")
    if (not isinstance(waivers, list) or not waivers
            or not all(isinstance(w, str) and w.strip() for w in waivers)):
        raise NoVerdict("config %s has no checklist.waivers list of names" % path)
    pattern = block.get("permalink_pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise NoVerdict("config %s has no checklist.permalink_pattern: the pattern a chat "
                        "message permalink matches on the install's chat transport" % path)
    try:
        permalink = re.compile(pattern)
    except re.error as e:
        raise NoVerdict("config %s: checklist.permalink_pattern does not compile: %s" % (path, e))
    figma = cfg.get("figma")
    if not isinstance(figma, dict) or "file_key" not in figma:
        raise NoVerdict("config %s has no figma.file_key: set it to the design file's key, or to "
                        "null for a project with no design file" % path)
    key = figma["file_key"]
    if key is not None and not (isinstance(key, str) and key.strip()):
        raise NoVerdict("config %s: figma.file_key is neither a design file's key nor null" % path)
    d = block.get("dir")
    return ([w.strip() for w in waivers], (d.strip() if isinstance(d, str) and d.strip() else None),
            permalink, key is not None)


def served_head(path):
    """(path, HEAD sha) of the worktree a build is served from, or NoVerdict."""
    if not os.path.isdir(path) or git(path, "rev-parse", "--show-toplevel")[0] != 0:
        raise NoVerdict("--served %s is not a git worktree" % path)
    rc, head = git(path, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if rc != 0 or not head:
        raise NoVerdict("--served %s has no HEAD commit that resolves" % path)
    return path, head


def load_rules(path):
    try:
        with open(path, encoding="utf-8") as f:
            rules = sorted({int(m.group(1)) for m in
                            (RULE_TABLE_ROW.match(l) for l in f) if m})
    except OSError as e:
        raise NoVerdict("%s unreadable: %s" % (path, e))
    if not rules:
        raise NoVerdict("no rule numbers found in %s's rule table (rows written "
                        "`| **N** | ... |`)" % path)
    return rules


def collect(paths, expect):
    """(files to check, missing expected slugs)."""
    files = []
    looked = []
    for p in paths:
        if os.path.isdir(p):
            looked.append(p)
            for name in sorted(os.listdir(p)):
                full = os.path.join(p, name)
                if not name.endswith(".md") or name.startswith(".") or not os.path.isfile(full):
                    continue
                if expect and name[:-3] not in expect:
                    continue
                files.append(full)
        else:
            files.append(p)
    stems = {os.path.splitext(os.path.basename(f))[0] for f in files}
    missing = [s for s in expect if s not in stems]
    return files, missing, looked


def main(argv):
    ap = argparse.ArgumentParser(
        description="Check feature checklists (see this file's header).")
    ap.add_argument("paths", nargs="+", metavar="checklist-or-directory")
    ap.add_argument("--expect", action="append", default=[], metavar="SLUG")
    ap.add_argument("--served", metavar="WORKTREE")
    ap.add_argument("--config", help="the config to read instead of the install's "
                    "(default: fleet where definition-of-done config.json)")
    args = ap.parse_args(argv)  # a usage error exits 2 from here
    expect = []
    for e in args.expect:
        expect.extend(s.strip() for s in e.split(",") if s.strip())
    files, missing, looked = collect(args.paths, expect)
    single = len(files) == 1

    try:
        config = args.config or default_config()
        waivers, checklist_dir, permalink, design = load_config(config)
        rules = load_rules(SKILL_MD)
        served = served_head(args.served) if args.served else None
        if served and single and not checklist_dir:
            raise NoVerdict("config %s has no checklist.dir, which --served needs to tell "
                            "a checklist commit from a code change" % config)
    except NoVerdict as e:
        print("NO VERDICT: %s" % e, file=sys.stderr)
        return 2
    if not design:
        print("NOTE: figma.file_key is null in %s: no design file, so sections 1a, 1b, 1c "
              "and 4 may be empty" % config)
    worst = 0
    counts = {"pass": 0, "findings": 0, "noverdict": 0}
    handoffs = []
    for path in files:
        c = Checklist(path, waivers, rules, permalink, design)
        try:
            c.check()
            if served:
                c.check_served(served, single, checklist_dir)
        except NoVerdict as e:
            print("NO VERDICT %s: %s" % (c.path, e))
            counts["noverdict"] += 1
            worst = 2
            continue
        except Exception as e:  # noqa: BLE001 - a crash is NO VERDICT, never "findings"
            print("NO VERDICT %s: internal error: %r" % (c.path, e))
            counts["noverdict"] += 1
            worst = 2
            continue
        if c.findings:
            for ln, msg in sorted(c.findings, key=lambda f: f[0]):
                print("%s:%d: %s" % (c.path, ln, msg))
            print("FINDINGS %s: %d - not passed" % (c.path, len(c.findings)))
            counts["findings"] += 1
            worst = max(worst, 1)
        else:
            at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            print("PASS %s: run by %s, builder %s, on %s" % (
                c.path, c.runner, c.builder, c.head))
            print("  record in its section 6: | %s | %s | %s |" % (c.runner, c.head, at))
            counts["pass"] += 1
            if c.handoff:
                handoffs.append(c.handoff[1])
    for slug in missing:
        print("MISSING %s: no checklist named %s.md in %s" % (
            slug, slug, ", ".join(looked) or "the files given"))
        worst = max(worst, 1)
    if not files and not missing:
        print("NO VERDICT: no checklist found in %s - a run that checked nothing "
              "is not a pass" % ", ".join(args.paths), file=sys.stderr)
        return 2
    if len(files) + len(missing) > 1:
        print("RESULT: %d checked - %d passed, %d with findings, %d no verdict; "
              "%d missing - exit %d" % (len(files), counts["pass"], counts["findings"],
                                         counts["noverdict"], len(missing), worst))
    if served and worst == 0:
        print("SERVED %s at %s: contains the hand-off commit(s) %s%s" % (
            served[0], served[1], ", ".join(sorted(set(handoffs))),
            "; nothing but checklists changed since" if single else ""))
    return worst


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - Python's own exit 1 would read as "findings"
        print("NO VERDICT: internal error: %r" % (e,), file=sys.stderr)
        sys.exit(2)
