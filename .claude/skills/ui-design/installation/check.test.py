#!/usr/bin/env python3
"""Regression guard for ui-design/installation/check.

Runs the real check as a subprocess from the root of a COPY of the fleet's
fixture install (FLEET_CONTEXT_ROOT set to that copy; HOME and the XDG
directories inside a temporary directory), so every verdict is exercised end to
end with no real install, no network and nothing written to the fixture.

THREE OUTCOMES, NEVER COLLAPSED:

  PASS        exit 0. Every green case is OK with the words it owes, and every
              planted fault went red with the verdict and the words its leg owes.
  FAIL        exit 1. A green case is not OK, or a fault went red the wrong way:
              the wrong code, the wrong row named, or another row named beside it.
  NO VERDICT  exit 3. A planted fault came back OK. That control cannot go red,
              so the check cannot fail for that reason, and the green cases say
              nothing about it. This is reported even when other cases FAIL,
              and it is never a pass: a green whose own control is green is the
              instrument reporting that it runs, not that the check measures.

WHAT EACH CASE PINS, and what deleting it would let through (the legs are the
check's header):

  green     the fixture install as committed, and a copy of it, are OK with
            SKILL.md's version (read here, independently) and the copy's own
            CONTEXT.md path: the path is the positive evidence that the check
            read the install FLEET_CONTEXT_ROOT selects, not some other one.
            `bash check` gives the same verdict (the hand-off line). The design
            and link registry forms are OK and say "not opened"; the optional
            row may be absent; a row of the install's own is ignored; an
            escaped pipe is part of a value; an autolink is a value; an old map
            inside an HTML comment or a fenced example beside the real one is
            not a second map.
  link      run through a symlink to the skill directory (an agent's skill
            link), from a copy of the fleet tree with bytecode writing allowed:
            OK, and no __pycache__ appears in the copy. abspath instead of
            realpath fails to import fleetlib; a missing dont_write_bytecode
            writes into the read-only fleet tree.
  file      CONTEXT.md removed: NOT INSTALLED naming its path.
  rows      each required row removed in turn: NOT INSTALLED naming THAT label
            alone. One value empty (also a mark that is only a space), one a
            placeholder (also in the optional row). A label twice, in one table,
            in a second table under the heading, or in a table elsewhere in the
            file: NOT INSTALLED naming it, never first-wins or last-wins.
  table     no heading, the heading or the table only inside a fence, an HTML
            comment or indented code, prose where the table was, no separator
            row, two headings, a header or a row with more than two cells (an
            unescaped pipe in a value), non-UTF-8 bytes: NO VERDICT.
  registry  another form word, `doc` with no path, a link with no scheme, a
            design id with a space: NOT INSTALLED.
  doc       a missing file, an empty file, a file of only whitespace, a
            directory, and a path outside the install that EXISTS and holds
            bytes (so only the containment leg can make it red, never the open):
            NOT INSTALLED naming it.
  key       the Design file row is the file's key as its first word, then
            optionally a link in any form, with or without definition-of-done:
            a row that starts with a link (a URL, a Markdown link, an autolink)
            is NOT INSTALLED, even when the link carries the key. A key followed
            by a Markdown link, an autolink or a link with no scheme, and a
            bare key, are OK. The link is never parsed: these are the review's
            probes, a URL of another file whose path carries the key and an
            unrelated host carrying it, which a URL parse read as the same file.
  pairs     with definition-of-done's config.json in the install context, each
            of the five shared values changed in turn: NOT INSTALLED naming that
            pair alone. Another key first with a link that carries the right
            one, a mark that lost its trailing space, a mark with one space too
            many, and a null file_key are mismatches. Whitespace around a key
            or a page id, on either side, is not a difference; a mark compares
            exactly. The config absent: OK, and the line says nothing was
            compared. The config not JSON, or missing a key: NO VERDICT.
  context   FLEET_CONTEXT_ROOT at a directory with no manifest: NO VERDICT.
  template  INSTRUCTION.md's template table carries exactly the check's labels,
            in its order; every value in it is wholly a placeholder, and the
            registry's hint names no form a fragment of it could be copied as;
            written as a CONTEXT.md unedited it is NOT INSTALLED naming every
            row as a placeholder. Its definition-of-done table names exactly the
            check's pairs. Without this the template and the check can
            disagree, and a template copied unfilled can read configured.

Run: python3 .claude/skills/ui-design/installation/check.test.py
"""
import atexit
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
INSTRUCTION = os.path.join(HERE, "INSTRUCTION.md")
SKILL_DIR = os.path.dirname(HERE)
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
REL_CTX = os.path.join(".claude", "skills", "ui-design", "CONTEXT.md")
REL_DOD = os.path.join(".claude", "skills", "definition-of-done", "config.json")
REGISTRY = "docs/screen-numbers.md"

for rel in (REL_CTX, REL_DOD):
    if not os.path.isfile(os.path.join(FIXTURE_INSTALL, rel)):
        print(f"NO VERDICT: the fixture install has no {rel}, so there is nothing to copy")
        sys.exit(3)
with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
    VERSION = int(re.search(r"^version:\s*(\d+)\s*$", f.read(), re.M).group(1))

_loader = importlib.machinery.SourceFileLoader("ui_design_check", CHECK)
_spec = importlib.util.spec_from_loader("ui_design_check", _loader)
SUBJECT = importlib.util.module_from_spec(_spec)
_loader.exec_module(SUBJECT)  # top level only: main() runs under __main__
LABELS = [label for label, _ in SUBJECT.ROWS]
REQUIRED = [label for label, req in SUBJECT.ROWS if req]
PAIRS = [(p[0], p[1]) for p in getattr(SUBJECT, "PAIRS", ())]  # (label, keys); a third field is how it compares

# realpath: on macOS $TMPDIR is a symlink (/var -> /private/var).
TMP = os.path.realpath(tempfile.mkdtemp(prefix="ui-design-check-test-"))
atexit.register(shutil.rmtree, TMP, True)  # removed on a failing or crashing run too
FAILED, CONTROL_PASSED = [], []

BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("FLEET_CONTEXT_ROOT", "FLEET_HOST_CONFIG", "CLAUDE_CONFIG_DIR",
                         "PYTHONDONTWRITEBYTECODE")}
BASE_ENV["HOME"] = os.path.join(TMP, "home")
for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    BASE_ENV[var] = os.path.join(TMP, "home", var.lower())
os.makedirs(BASE_ENV["HOME"])

with open(os.path.join(FIXTURE_INSTALL, REL_DOD), encoding="utf-8") as f:
    DOD_FIGMA = json.load(f)["figma"]


def install(name, edit=None, dod=None):
    """A copy of the fixture install. `edit` maps its CONTEXT.md text to new text;
    `dod` maps its definition-of-done config (parsed) to a new one, or is the
    string "absent" or raw text to write in its place."""
    root = os.path.join(TMP, name)
    shutil.copytree(FIXTURE_INSTALL, root)
    if edit:
        path = os.path.join(root, REL_CTX)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = edit(text)
        if new == text:
            raise SystemExit(f"test bug: the edit for {name!r} changed nothing")
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    if dod is not None:
        path = os.path.join(root, REL_DOD)
        if dod == "absent":
            os.remove(path)
        elif isinstance(dod, str):
            with open(path, "w", encoding="utf-8") as f:
                f.write(dod)
        else:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            dod(cfg)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
    return root


def run(root, argv=(), shell=False, check=CHECK, env_extra=None):
    env = dict(BASE_ENV, FLEET_CONTEXT_ROOT=root, **(env_extra or {}))
    cmd = (["bash", check] if shell else [sys.executable, check]) + list(argv)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=root)
    return p.returncode, (p.stdout + p.stderr).strip()


def row(label, value=None):
    """An edit that sets LABEL's value, or removes its row when value is None."""
    pat = re.compile(r"^\| %s \|[^\n]*\n" % re.escape(label), re.M)

    def edit(text):
        return pat.sub("" if value is None else lambda m: f"| {label} | {value} |\n", text, count=1)
    return edit


def setkey(keys, value):
    """A dod edit that sets figma.<keys> to value."""
    def edit(cfg):
        d = cfg["figma"]
        for k in keys[:-1]:
            d = d[k]
        d[keys[-1]] = value
    return edit


def dropkey(keys):
    def edit(cfg):
        d = cfg["figma"]
        for k in keys[:-1]:
            d = d[k]
        del d[keys[-1]]
    return edit


def green(name, root, needles, **kw):
    code, text = run(root, **kw)
    ok = code == 0 and text.startswith(f"OK: configured (version {VERSION})") and all(n in text for n in needles)
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f" - {code}: {text}"))
    if not ok:
        FAILED.append(name)


def red(name, root, code_want, needles, absent=(), **kw):
    """A planted fault. Back as OK: the control passed (NO VERDICT). Back red the wrong way: FAIL."""
    code, text = run(root, **kw)
    if code == 0:
        print(f"[NO VERDICT] {name} - the planted fault came back OK: {text}")
        CONTROL_PASSED.append(name)
        return
    ok = code == code_want and all(n in text for n in needles) and not any(a in text for a in absent) \
        and "Traceback" not in text
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f" - {code}: {text}"))
    if not ok:
        FAILED.append(name)


def fact(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else f" - {detail}"))
    if not cond:
        FAILED.append(name)


NOT, NOV = "NOT INSTALLED", "NO VERDICT"
MAP = "## Design map"


def before_map(extra):
    return lambda t: t.replace(MAP, extra + "\n\n" + MAP, 1)


def section(text):
    """The design map section of a fixture CONTEXT.md, heading to end."""
    return text[text.index(MAP):]


def hide_map(wrap):
    """An edit that wraps the whole design map section in `wrap(section)`."""
    return lambda t: t[:t.index(MAP)] + wrap(section(t))


# ----------------------------------------------------------------- green
good = install("good")
green("the fixture install copy is OK, naming its own CONTEXT.md and the registry it opened",
      good, [os.path.join(good, REL_CTX), f"registry doc {REGISTRY} opened and read",
             "design-tool skills: none", "agrees with definition-of-done's config.json on 5 values"])
green("the committed fixture install, in place, is OK", FIXTURE_INSTALL, [f"registry doc {REGISTRY}"])
green("bash check gives the same verdict as python3 check", good, [f"registry doc {REGISTRY}"], shell=True)
green("a design registry is OK, recorded and not opened",
      install("design", row("Screen-number registry", "design `1005:1`")),
      ["registry recorded as design 1005:1, not opened"])
green("a link registry is OK, recorded and not opened",
      install("link", row("Screen-number registry", "link https://wiki.example.com/screens")),
      ["registry recorded as link https://wiki.example.com/screens, not opened"])
green("an autolink registry is a value, not a placeholder",
      install("autolink", row("Screen-number registry", "link <https://wiki.example.com/screens>")),
      ["registry recorded as link https://wiki.example.com/screens, not opened"])
KEY = DOD_FIGMA["file_key"]
AGREES = ["agrees with definition-of-done"]
green("the key followed by a Markdown link is OK",
      install("key-mdlink", row("Design file", f"{KEY} [Example](https://design.example.com/file/{KEY}/Example)")), AGREES)
green("the key followed by a link with no scheme is OK",
      install("key-noscheme", row("Design file", f"{KEY} design.example.com/file/{KEY}/Example")), AGREES)
green("the key followed by an autolink is OK",
      install("key-autolink", row("Design file", f"`{KEY}` <https://design.example.com/file/{KEY}/Example>")), AGREES)
green("the bare key in backticks is OK", install("barekey", row("Design file", f"`{KEY}`")), AGREES)
green("the bare key with no backticks is OK", install("barekey-plain", row("Design file", KEY)), AGREES)
green("spaces inside the key's backticks are not a difference",
      install("key-spaced", row("Design file", f"`{KEY} ` https://design.example.com/x")), AGREES)
green("a definition-of-done file_key with a trailing space is not a difference",
      install("dodkey-space", dod=setkey(("file_key",), KEY + " ")), AGREES)
green("a definition-of-done page id with spaces around it is not a difference",
      install("dodpage-space", dod=setkey(("pages", "current"), " " + DOD_FIGMA["pages"]["current"] + " ")), AGREES)
green("a map page id with a space inside its backticks is not a difference",
      install("mappage-space", row("Approved page", f"` {DOD_FIGMA['pages']['incoming']}`")), AGREES)
green("the optional row may be absent", install("notools", row("Design-tool skills")),
      ["design-tool skills: not recorded"])
green("a row of the install's own is ignored",
      install("ownrow", lambda t: t.replace("| Design-tool skills |", "| Call cap | 20 a month |\n| Design-tool skills |")),
      ["11 required values"])
green("an escaped pipe is part of a value",
      install("escaped", row("Design-tool skills", r"example-tool \| example-export")),
      ["design-tool skills: example-tool | example-export"])
green("an old map inside an HTML comment is not a second map",
      install("oldcomment", lambda t: t.replace(MAP, "<!--\n" + section(t).replace("Ada Example", "Old Example") + "-->\n\n" + MAP, 1)),
      ["agrees with definition-of-done"])
green("a fenced example map is not a second map",
      install("oldfence", lambda t: t.replace(MAP, "```markdown\n" + section(t) + "```\n\n" + MAP, 1)),
      ["agrees with definition-of-done"])
green("with no definition-of-done config.json, nothing is compared, and the line says so",
      install("nodod", dod="absent"), ["no definition-of-done config.json, nothing compared"])

# A skill link into a copy of the fleet tree, with bytecode writing allowed.
fleet_copy = os.path.join(TMP, "fleet-copy")
shutil.copytree(os.path.join(FLEET_ROOT, "lib", "fleetlib"), os.path.join(fleet_copy, "lib", "fleetlib"),
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(SKILL_DIR, os.path.join(fleet_copy, ".claude", "skills", "ui-design"),
                ignore=shutil.ignore_patterns("__pycache__"))
link_dir = os.path.join(TMP, "agent-home", ".claude", "skills")
os.makedirs(link_dir)
os.symlink(os.path.join(fleet_copy, ".claude", "skills", "ui-design"), os.path.join(link_dir, "ui-design"))
green("through an agent's skill link, from a copy of the fleet tree, it is OK", good,
      [f"registry doc {REGISTRY}"], check=os.path.join(link_dir, "ui-design", "installation", "check"))
caches = [d for d, _, _ in os.walk(fleet_copy) if os.path.basename(d) == "__pycache__"]
fact("... and it wrote no bytecode into the fleet tree", not caches, str(caches))

# ------------------------------------------------------------- file, rows
gone = install("absent")
os.remove(os.path.join(gone, REL_CTX))
red("no CONTEXT.md is NOT INSTALLED, naming its path", gone, 2, [NOT, os.path.join(gone, REL_CTX)])
for label in REQUIRED:
    others = [f"missing: {o}" for o in REQUIRED if o != label]
    red(f"the {label!r} row missing is NOT INSTALLED naming it alone",
        install("missing-" + re.sub(r"\W", "", label), row(label)), 2, [NOT, f"missing: {label}. Follow"], others)
red("an empty value is NOT INSTALLED", install("empty", row("Design approver", "")), 2,
    [NOT, "empty: Design approver. Follow"])
red("a mark that is only a space is NOT INSTALLED", install("emptymark", row("In-build mark", "` `")), 2,
    [NOT, "empty: In-build mark"])
red("a placeholder value is NOT INSTALLED",
    install("placeholder", row("Implemented page", "<id of page 3, implemented and merged>")), 2,
    [NOT, "still a <placeholder>: Implemented page. Follow"])
red("a placeholder in the optional row is NOT INSTALLED",
    install("placeholder-opt", row("Design-tool skills", "<their names, or none>")), 2,
    [NOT, "still a <placeholder>: Design-tool skills. Follow"])
red("a row repeated in the table is NOT INSTALLED, naming it",
    install("repeated", lambda t: t.replace("| Approved page |", "| Drafts page | `300:1` |\n| Approved page |")),
    2, [NOT, "repeated: Drafts page (lines"])
red("a label in a second table under the heading is NOT INSTALLED, naming it",
    install("secondtable", lambda t: t + "\n| Value | Setting |\n|---|---|\n| Scratch area | `400:2` |\n"),
    2, [NOT, "repeated: Scratch area (lines"])
red("a label in a table elsewhere in the file is NOT INSTALLED, naming it",
    install("elsewhere", before_map("## Notes\n\n| Value | Setting |\n|---|---|\n| Design file | https://design.example.com/file/OTHER/x |")),
    2, [NOT, "repeated: Design file (lines"])

# ------------------------------------------------------------------ table
red("no '## Design map' heading is NO VERDICT",
    install("noheading", lambda t: t.replace(MAP, "## Design table")), 1, [NOV, "no '## Design map' heading"])
red("the map only inside a fence is NO VERDICT",
    install("fenced", hide_map(lambda s: "```markdown\n" + s + "```\n")), 1, [NOV, "no '## Design map' heading"])
red("the map only inside an HTML comment is NO VERDICT",
    install("commented", hide_map(lambda s: "<!--\n" + s + "-->\n")), 1, [NOV, "no '## Design map' heading"])
red("the map only as indented code is NO VERDICT",
    install("indented", hide_map(lambda s: "".join("    " + l if l.strip() else l for l in s.splitlines(True)))),
    1, [NOV, "no '## Design map' heading"])
red("the table only inside an HTML comment is NO VERDICT",
    install("tablecomment", lambda t: t.replace("| Value | Setting |", "<!--\n| Value | Setting |", 1) + "-->\n"),
    1, [NOV, "no pipe table"])
red("the table only as indented code is NO VERDICT",
    install("tableindented", lambda t: re.sub(r"^\|", "    |", t, flags=re.M)), 1, [NOV, "no pipe table"])
red("prose where the table was is NO VERDICT",
    install("prose", lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("|"))), 1, [NOV, "no pipe table"])
red("no separator row is NO VERDICT",
    install("noseparator", lambda t: t.replace("|---|---|\n", "")), 1, [NOV, "no pipe table"])
red("two '## Design map' headings are NO VERDICT",
    install("twoheadings", lambda t: t + "\n## Design map\n\nnone\n"), 1, [NOV, "2 '## Design map' headings"])
red("a row with an unescaped pipe in its value is NO VERDICT, naming the row",
    install("extracell", row("Design-tool skills", "example-tool | example-export")), 1,
    [NOV, "row 'Design-tool skills'", "3 cells"])
red("a header of three columns is NO VERDICT",
    install("threecols", lambda t: t.replace("| Value | Setting |\n|---|---|", "| Value | Setting | Note |\n|---|---|---|")),
    1, [NOV, "header", "3 cells"])
undec = install("undecodable")
with open(os.path.join(undec, REL_CTX), "ab") as f:
    f.write(b"\xff\xfe\n")
red("a CONTEXT.md that is not UTF-8 is NO VERDICT", undec, 1, [NOV, "not UTF-8"])

# --------------------------------------------------------- registry, doc
for label, value, needle in (
        ("another form word", "wiki https://wiki.example.com/screens", "none of the three forms"),
        ("doc with no path", "doc", "'doc' takes a repository-relative path"),
        ("a link with no scheme", "link wiki.example.com/screens", "'link' takes a URL"),
        ("a design id with a space", "design 1005 1", "'design' takes one id with no space")):
    red(f"{label} is NOT INSTALLED", install("form-" + re.sub(r"\W", "", label), row("Screen-number registry", value)),
        2, [NOT, needle])
red("a doc registry naming a missing file is NOT INSTALLED, naming it",
    install("doc-missing", row("Screen-number registry", "doc docs/no-such-registry.md")), 2,
    [NOT, "docs/no-such-registry.md", "cannot be read"])
empty_doc = install("doc-empty", row("Screen-number registry", "doc docs/empty-registry.md"))
open(os.path.join(empty_doc, "docs", "empty-registry.md"), "w").close()
red("a doc registry naming an empty file is NOT INSTALLED", empty_doc, 2, [NOT, "empty-registry.md holds no text"])
blank_doc = install("doc-blank", row("Screen-number registry", "doc docs/blank-registry.md"))
with open(os.path.join(blank_doc, "docs", "blank-registry.md"), "w") as f:
    f.write(" \n\t\n" * 20000)  # past one read chunk, so the scan is proven to keep going
red("a doc registry of only whitespace is NOT INSTALLED", blank_doc, 2, [NOT, "blank-registry.md holds no text"])
red("a doc registry naming a directory is NOT INSTALLED",
    install("doc-dir", row("Screen-number registry", "doc docs")), 2, [NOT, "'doc docs'", "cannot be read"])
with open(os.path.join(TMP, "outside-registry.md"), "w") as f:
    f.write("| 01 | a registry that exists, outside the install |\n")
red("a doc registry outside the install (the file exists) is NOT INSTALLED",
    install("doc-outside", row("Screen-number registry", "doc ../outside-registry.md")), 2,
    [NOT, "outside the install repository"])
red("a doc registry at an absolute path (the file exists) is NOT INSTALLED",
    install("doc-absolute", row("Screen-number registry", "doc " + os.path.join(TMP, "outside-registry.md"))), 2,
    [NOT, "outside the install repository"])

# ------------------------------------------------------------------ pairs
fact("the check pairs five design-map rows with definition-of-done keys", len(PAIRS) == 5, repr(PAIRS))
for label, keys in PAIRS:
    dotted = "figma." + ".".join(keys)
    others = [f"{o} differs" for o, _ in PAIRS if o != label]
    red(f"{dotted} differing from the {label!r} row is NOT INSTALLED naming that pair alone",
        install("pair-" + re.sub(r"\W", "", label), dod=setkey(keys, "EXAMPLE-DIFFERENT")), 2,
        [NOT, f"{label} differs from definition-of-done's {dotted}"], others)
DIFFERS_KEY = [NOT, "Design file differs from definition-of-done's figma.file_key"]
FIRST_WORD = [NOT, "Design file", "must start with the design file's key"]
red("another file's key first, with a link that carries the right key, is a mismatch",
    install("pair-otherkey", row("Design file", f"OtherFileKey999 https://design.example.com/file/OtherFileKey999/{KEY}")),
    2, DIFFERS_KEY)
red("a key that only starts like the right one is a mismatch",
    install("pair-prefix", row("Design file", f"{KEY}X https://design.example.com/file/{KEY}X/Example")), 2, DIFFERS_KEY)
red("a URL of another file whose path carries the key is NOT INSTALLED (no key first)",
    install("url-otherfile", row("Design file", f"https://design.example.com/file/OtherFileKey999/{KEY}")), 2, FIRST_WORD)
red("an unrelated host carrying the key is NOT INSTALLED (no key first)",
    install("url-unrelated", row("Design file", f"https://unrelated.example.org/{KEY}")), 2, FIRST_WORD)
red("a Markdown link with no key first is NOT INSTALLED",
    install("url-mdlink", row("Design file", f"[Example](https://design.example.com/file/{KEY}/Example)")), 2, FIRST_WORD)
red("an autolink with no key first is NOT INSTALLED",
    install("url-autolink", row("Design file", f"<https://design.example.com/file/{KEY}/Example>")), 2, FIRST_WORD)
red("with no definition-of-done config.json, a link with no key first is still NOT INSTALLED",
    install("url-nodod", row("Design file", f"https://design.example.com/file/{KEY}/Example"), dod="absent"), 2,
    FIRST_WORD)
red("a definition-of-done key with a trailing space, against another key, is a mismatch",
    install("dodkey-space-other", dod=setkey(("file_key",), "OtherFileKey999 ")), 2, DIFFERS_KEY)
red("a mark with one space too many is a mismatch",
    install("pair-space2", row("In-build mark", f"`{DOD_FIGMA['in_build_marker_prefix']} `")),
    2, [NOT, "In-build mark differs from definition-of-done's figma.in_build_marker_prefix"])
red("a mark written without backticks loses its trailing space, and is a mismatch",
    install("pair-space", row("In-build mark", DOD_FIGMA["in_build_marker_prefix"].strip())),
    2, [NOT, "In-build mark differs from definition-of-done's figma.in_build_marker_prefix"])
red("a null figma.file_key (no design file) beside a design map is NOT INSTALLED",
    install("pair-null", dod=setkey(("file_key",), None)), 2, [NOT, "figma.file_key is null"])
red("a definition-of-done config.json that is not JSON is NO VERDICT",
    install("pair-notjson", dod="{ not json"), 1, [NOV, "definition-of-done"])
red("a definition-of-done config.json missing a shared key is NO VERDICT",
    install("pair-nokey", dod=dropkey(("pages", "current"))), 1, [NOV, "figma.pages.current"])

# ----------------------------------------------------------------- context
bare = os.path.join(TMP, "no-manifest")
os.makedirs(bare)
red("FLEET_CONTEXT_ROOT with no manifest is NO VERDICT", bare, 1, [NOV, "no install context"])
red("an argument is NO VERDICT (usage)", good, 1, [NOV, "usage"], argv=["--online"])

# ---------------------------------------------------------------- template
with open(INSTRUCTION, encoding="utf-8") as f:
    instruction = f.read()
blocks = re.findall(r"^```markdown\n(.*?)^```$", instruction, re.M | re.S)
template = next((b for b in blocks if b.startswith(MAP + "\n")), None)
if template is None:
    fact("INSTRUCTION.md carries a ```markdown block starting '## Design map'", False)
else:
    table = [l for l in template.split("\n") if l.startswith("|")]
    pairs = [[c.strip() for c in l.split("|")[1:-1]] for l in table[2:]]
    got = [p[0] for p in pairs]
    fact("INSTRUCTION.md's template carries exactly the check's labels, in order", got == LABELS,
         f"template {got}, check {LABELS}")
    loose = [label for label, value in pairs if not re.fullmatch(r"`?<[^<>@]+>`?", value)]
    fact("every value in the template is wholly a <placeholder>", not loose, f"not a placeholder: {loose}")
    reg = dict((p[0], p[1]) for p in pairs).get("Screen-number registry", "")
    fact("the registry's placeholder names no form a fragment of it could be copied as",
         not re.search(r"\b(?:doc|design|link)\s+\S", reg, re.I), reg)
    unedited = install("template", lambda t: t[:t.index(MAP)] + template)
    red("the template written unedited is NOT INSTALLED, every row a placeholder", unedited, 2,
        [NOT, f"still a <placeholder>: {', '.join(LABELS)}. Follow"])
m = re.search(r"^\| Design map row \| definition-of-done `config.json` key \|\n\|[-|]+\|\n((?:\|.*\|\n)+)",
              instruction, re.M)
listed = [tuple(c.strip().strip("`") for c in l.split("|")[1:3]) for l in m.group(1).splitlines()] if m else []
fact("INSTRUCTION.md's definition-of-done table names exactly the check's pairs",
     bool(listed) and listed == [(label, "figma." + ".".join(keys)) for label, keys in PAIRS],
     f"{listed} vs {PAIRS}")

print()
if CONTROL_PASSED:
    print(f"NO VERDICT: {len(CONTROL_PASSED)} planted fault(s) came back OK, so the check cannot fail for "
          f"those reasons and its green says nothing about them: " + "; ".join(CONTROL_PASSED)
          + (f". Also {len(FAILED)} FAILED: " + "; ".join(FAILED) if FAILED else ""))
    sys.exit(3)
if FAILED:
    print(f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    sys.exit(1)
print("ALL CHECKS PASSED")
