#!/usr/bin/env python3
"""gates.py - the fleet's structural gates, one mode per gate.

Usage: python3 tests/gates/gates.py <gate>
       (each tests/gates/<gate>.test.sh is a one-line wrapper; tests/gates/run.sh
       runs them all, and CI's gates job runs run.sh)

Gates (design 4.12):
  skill-references  every backticked `/name` in fleet prose resolves to
                    .claude/skills/<name>/SKILL.md, unless NOT_SKILLS names it;
                    and fleet prose never names an install's skill where a
                    conventions key belongs (INSTALL_SKILLS)
  bash-safe         every extensionless Python script carries, as line 2, the
                    shell hand-off line claude-skill section 3 prints, byte for byte
  layout            no SPECIFIC file under .claude/skills/ (CONTEXT.md,
                    config.json, installation/.install-state.json, temporary/),
                    no .claude/agents/ or .claude-plugin/ directory, no committed
                    .gitleaks.toml or .gitleaksignore (gitleaks honours a root
                    .gitleaks.toml, which would weaken the leak gate), no
                    symlink whose target is absolute, leaves the repository or is
                    missing; and no Claude Code configuration beyond the one the
                    repository ships: .claude/settings.json is byte for byte
                    SETTINGS_PIN, and there is no CLAUDE.md or CLAUDE.local.md
                    (at any depth: a session loads one when it reads that
                    directory), no .mcp.json and no .claude/settings.local.json.
                    A session started in a fleet checkout runs that
                    configuration with no trust prompt in `claude -p`
  ascii             every byte of fleet prose is ASCII
  frontmatter       every SKILL.md frontmatter parses with the restricted parser
                    below and carries non-empty name, version and description,
                    name equal to the skill's directory
  actions-pinned    every `uses:` in .github/ names a full 40-hex commit SHA (a
                    local ./action needs none; docker:// needs a sha256 digest)
  workflow-safety   every workflow under .github/workflows/ triggers on push,
                    pull_request and workflow_dispatch only, sets permissions
                    contents: read at the top and nowhere per job, names no
                    secret, and every job carries the exact fork gate `if:` and
                    a runs-on that is one of the two self-hosted label sets
                    (SELF_HOSTED); the reasons are at check_workflow_safety
  setup-checklist   SETUP.md's closing checklist names exactly the keys of
                    templates/fleet.example.json and of each skill's
                    config.example.json (a <placeholder> segment stands for a
                    key that is data, such as a user id; a conventions value is
                    one key, being an object by contract); and, under a heading
                    naming each tracked unit template (*.service.example, and
                    the launchd form *.plist.example), every <placeholder> that
                    template carries, with no token the template does not
                    contain (a template whose tokens carry no angle brackets,
                    filled by a sed, is held to the second half, and a heading
                    that lists no token is a finding). In a plist, a <name>
                    whose closing tag </name> the file also carries is one of
                    its XML elements (<key>, <string>), not a placeholder
  portable-shell    no tracked shell script (*.sh, *.bash, or an extensionless
                    file whose shebang names sh, bash or zsh) and no ```bash,
                    ```sh, ```shell or ```zsh block of a tracked Markdown file
                    (outside fixtures/) uses what macOS's bash 3.2 or its BSD
                    userland cannot run: grep -P, stat -c, sed -i, date -d,
                    find -printf, timeout, setsid or flock as a command,
                    declare -A, mapfile, readarray, ${x,,} and ${x^^}, |& and
                    &>>, and an apostrophe in the word of a double-quoted
                    ${x:-word} (bash 3.2 does not parse the file; SHELL_RULES).
                    A command line (joined across a trailing
                    backslash) that carries `# linux-only: <reason>` is exempt;
                    a mark with no reason is a finding. `stat -c` and `date -d`
                    pass when the same command line carries the BSD form as
                    the fallback (`stat -c ... || stat -f ...`). Comments are
                    not read
  starter-knowledge examples/knowledge-base passes the knowledge-base skill's
                    own check_indexes.py, and every lesson opens with the
                    '> EXAMPLE lesson - ' marker (design 4.14)

Fleet prose: every TRACKED .md file at the repository root or under
.claude/skills/, templates/ or examples/, except under a directory named
fixtures/ (fixtures are captured data, not prose).

Every gate reads tracked files only (git ls-files), with their working-tree
content. An untracked file is invisible: the gates judge committed trees.

The positive control, the reason a PASS means anything. Before judging the real
tree, each gate copies every tracked file into a fresh temporary repository,
injects faults (and decoys that must NOT be reported), and runs the SAME check
over the copy: the same git ls-files, the same file selection, the same
patterns. Each injected fault must come back as a finding naming its own path
and its own reason; a decoy that comes back is a false red. Either miss is
NO VERDICT, because a check that cannot see a planted fault cannot be trusted
about the real tree. The control injects into every region the gate claims to
read, so a selection that silently drops a region drops its control with it.

Exit codes: 0 PASS; 1 FAIL, every finding named as <path>[:<line>]: <reason>;
2 usage; 3 NO VERDICT (the control did not fire, or the instrument could not
be established). A non-zero exit is never green.

What no gate checks: untracked files; non-.md text under templates/ for the
prose gates; whether a resolved skill says anything useful; for portable-shell,
shell held in another file type (a Python string, a workflow's run: step,
whose runs-on names its system), an unlabelled fence, any bash 4 construct
SHELL_RULES does not list, and an apostrophe in a ${x:-word} inside a
double-quoted string or heredoc body that opened on an earlier line (the
quoting is walked one command line at a time).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NoVerdict(Exception):
    """The instrument could not be established; no PASS and no FAIL."""


# ---------------------------------------------------------------- the tree

def tracked(root):
    """Tracked paths that exist in the working tree (a symlink counts)."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=False)
    if out.returncode != 0:
        raise NoVerdict(f"git ls-files failed in {root}: {out.stderr.decode().strip()}")
    paths = [p for p in out.stdout.decode().split("\0") if p]
    return [p for p in paths if os.path.lexists(root / p)]


def is_prose(path):
    parts = path.split("/")
    if not path.endswith(".md") or "fixtures" in parts[:-1]:
        return False
    return len(parts) == 1 or parts[0] in ("templates", "examples") or path.startswith(".claude/skills/")


def prose(root):
    return [p for p in tracked(root) if is_prose(p) and not os.path.islink(root / p)]


def skills(root):
    """Loadable fleet skills: a tracked .claude/skills/<name>/SKILL.md."""
    names = sorted({p.split("/")[2] for p in tracked(root)
                    if re.fullmatch(r"\.claude/skills/[^/]+/SKILL\.md", p)})
    if not names:
        raise NoVerdict("no loadable skill found under .claude/skills/")
    return names


def lines_of(root, path):
    return (root / path).read_text(encoding="utf-8", errors="replace").split("\n")


# ------------------------------------------------------- skill-references

TOKEN = re.compile(r"`/([a-z][a-z0-9-]+)`")
# Backticked `/name` tokens that are not skill references, each with its
# reason. Two rules keep the list honest, both enforced: a row naming a fleet
# skill would silence that skill's references, and a row matching nothing in
# fleet prose is a lid over nothing; either is a finding.
NOT_SKILLS = {
    "compact": "Claude Code built-in command",
    "login": "Claude Code built-in command",
    "usage": "Claude Code built-in command",
    "schedule": "Claude Code built-in command (a cloud routine)",
    "loop": "Claude Code built-in command",
    "exit": "Claude Code built-in command",
    "proc": "absolute filesystem path",
    "run": "absolute filesystem path",
}
# Skills an install keeps for its own development process. Fleet prose cites
# the conventions key that points at one (CONVENTIONS.md), never the skill. A
# name in any `/name` form is refused; the hyphenated ones also when backticked
# bare (`release` is itself a conventions key, so only `/release` is refused).
INSTALL_SKILLS = ("definition-of-done", "worktree-workflow", "repo-and-environments",
                  "e2e-suite", "release")


def check_skill_references(root):
    names = skills(root)
    findings = [f".claude/skills/{n}: skill name outside [a-z][a-z0-9-]*, so no reference to it can be seen"
                for n in names if not re.fullmatch(r"[a-z][a-z0-9-]*", n)]
    known = set(names)
    seen = set()
    slash_install = re.compile(r"(?<![\w./-])/(%s)(?![\w-])" % "|".join(map(re.escape, INSTALL_SKILLS)))
    bare_install = re.compile(r"`(%s)`" % "|".join(re.escape(n) for n in INSTALL_SKILLS if "-" in n))
    for path in prose(root):
        for no, line in enumerate(lines_of(root, path), 1):
            for name in TOKEN.findall(line):
                seen.add(name)
                if name not in known and name not in NOT_SKILLS and name not in INSTALL_SKILLS:
                    findings.append(f"{path}:{no}: `/{name}` does not resolve to .claude/skills/{name}/SKILL.md")
            for m in list(slash_install.finditer(line)) + list(bare_install.finditer(line)):
                findings.append(f"{path}:{no}: names the install's skill '{m.group(1)}'; "
                                f"cite a conventions key (CONVENTIONS.md) instead")
    for name, reason in NOT_SKILLS.items():
        if name in known:
            findings.append(f"tests/gates/gates.py: NOT_SKILLS row '{name}' ({reason}) names a fleet skill; delete the row")
        elif name not in seen:
            findings.append(f"tests/gates/gates.py: NOT_SKILLS row '{name}' ({reason}) matches nothing in fleet prose; delete the row")
    return findings


def control_skill_references(copy):
    first = skills(copy)[0]
    skill_md = f".claude/skills/{first}/SKILL.md"
    append(copy, skill_md, "\nSee `/no-such-skill`.\n")
    created = {p: "See `/no-such-skill`.\n" for p in
               ("templates/zz-gate-control.md", "examples/zz-gate-control.md", "zz-gate-control.md")}
    for p, text in created.items():
        write(copy, p, text)
    append(copy, "README.md", "\nThe install's /definition-of-done applies.\n")
    # decoys: a path, an allowed built-in, a fixture's prose
    write(copy, f".claude/skills/{first}/zz-decoy.md", "Read `/etc/hosts`; type `/compact`.\n")
    write(copy, f".claude/skills/{first}/fixtures/zz-decoy.md", "See `/no-such-fixture-ref`.\n")
    expected = [(p, "`/no-such-skill` does not resolve") for p in [skill_md, *created]]
    expected.append(("README.md", "install's skill 'definition-of-done'"))
    return expected, ["no-such-fixture-ref", "/etc", "zz-decoy.md"]


# --------------------------------------------------------------- bash-safe

PY_SHEBANG = re.compile(r"#!.*\bpython[0-9.]*(\s|$)")


def handoff_line(root):
    """The line claude-skill section 3 prints: the one fenced line after 'byte for byte:'."""
    src = root / ".claude/skills/claude-skill/SKILL.md"
    if not src.is_file():
        raise NoVerdict(f"{src.relative_to(root)} is missing, so the hand-off line has no source")
    text = src.read_text(encoding="utf-8")
    m = re.search(r"byte for byte:\s*\n\s*```[^\n]*\n(.*?)\n```", text, re.S)
    if not m or "\n" in m.group(1) or not m.group(1).strip():
        raise NoVerdict("cannot read the hand-off line from claude-skill/SKILL.md: expected one "
                        "fenced line right after 'byte for byte:'")
    return m.group(1)


def check_bash_safe(root):
    want = handoff_line(root)
    findings = []
    for path in tracked(root):
        full = root / path
        if "." in path.rsplit("/", 1)[-1] or os.path.islink(full) or not full.is_file():
            continue
        head = full.read_bytes().decode("utf-8", errors="replace").split("\n")
        if not PY_SHEBANG.match(head[0]):
            continue
        if len(head) < 2 or head[1] != want:
            findings.append(f"{path}:2: an extensionless Python script whose line 2 is not the "
                            f"claude-skill section 3 hand-off line, byte for byte")
    return findings


def control_bash_safe(copy):
    lines = lines_of(copy, "bin/fleet")
    lines[1] = lines[1].replace("python3", "python", 1)
    write(copy, "bin/fleet", "\n".join(lines))
    write(copy, "zz-gate-control", "#!/usr/bin/python3\nprint('no hand-off')\n")
    first = skills(copy)[0]
    write(copy, f".claude/skills/{first}/zz-decoy", "#!/usr/bin/env bash\necho a bash script\n")
    write(copy, f".claude/skills/{first}/zz-decoy.py", "#!/usr/bin/env python3\nprint('has an extension')\n")
    expected = [("bin/fleet", "hand-off line"), ("zz-gate-control", "hand-off line")]
    return expected, ["zz-decoy"]


# ------------------------------------------------------------------ layout

SPECIFIC_EXEMPT = "tests/fixtures/install/"
SETTINGS = ".claude/settings.json"
# The one Claude Code configuration this repository ships, byte for byte (design
# 4.1): attribution off, nothing else. A hooks, env or apiKeyHelper key added
# here would run in every session started in a fleet checkout, `claude -p`
# sessions with no trust prompt included, so the merge of such a change is the
# gate and this pin is what makes it visible.
SETTINGS_PIN = b'{"attribution": {"commit": "", "pr": ""}}\n'


def check_layout(root):
    findings = []
    real_root = os.path.realpath(root)
    paths = tracked(root)
    shipped = (root / SETTINGS).read_bytes() if SETTINGS in paths else None
    if shipped != SETTINGS_PIN:
        findings.append(f"{SETTINGS}: not exactly the attribution-only content {SETTINGS_PIN.decode().strip()}; "
                        f"anything else in it runs in every session started in a checkout")
    for path in paths:
        parts = path.split("/")
        full = root / path
        if parts[-1] in ("CLAUDE.md", "CLAUDE.local.md"):
            findings.append(f"{path}: a CLAUDE.md; Claude Code loads it as instructions in any session that "
                            f"reads this directory")
        if parts[-1] == ".mcp.json":
            findings.append(f"{path}: a committed MCP server configuration; a session started here would "
                            f"connect its servers")
        if parts[-2:] == [".claude", "settings.local.json"]:
            findings.append(f"{path}: a committed Claude Code settings file; its hooks, env and apiKeyHelper "
                            f"would run in every session started here")
        for i in range(len(parts) - 1):
            if parts[i] == ".claude" and parts[i + 1] in ("agents",):
                findings.append(f"{path}: a .claude/agents/ directory; a session in this checkout would load it "
                                f"as an agent (persona templates live in templates/personas/)")
        if ".claude-plugin" in parts[:-1]:
            findings.append(f"{path}: a .claude-plugin/ directory; the fleet ships no plugin manifest")
        if parts[-1] in (".gitleaks.toml", ".gitleaksignore"):
            findings.append(f"{path}: a committed gitleaks configuration; gitleaks would honour it and the leak gate "
                            f"would run with rules nobody reviewed")
        skills_at = next((i for i in range(len(parts) - 2)
                          if parts[i] == ".claude" and parts[i + 1] == "skills"), None)
        if skills_at is not None and not path.startswith(SPECIFIC_EXEMPT):
            rest = parts[skills_at + 2:]
            if rest[-1] in ("CONTEXT.md", "config.json"):
                findings.append(f"{path}: a SPECIFIC file under .claude/skills/; it belongs in the install "
                                f"(fixtures under {SPECIFIC_EXEMPT})")
            elif rest[-2:] == ["installation", ".install-state.json"]:
                findings.append(f"{path}: an install-state file under .claude/skills/; it belongs in the install")
            elif "temporary" in rest[:-1]:
                findings.append(f"{path}: a temporary/ directory under .claude/skills/; it belongs in the install")
        if os.path.islink(full):
            target = os.readlink(full)
            resolved = os.path.realpath(full)
            if os.path.isabs(target):
                findings.append(f"{path}: a symlink with an absolute target")
            elif os.path.commonpath([real_root, resolved]) != real_root:
                findings.append(f"{path}: a symlink whose target leaves the repository")
            elif not os.path.exists(full):
                findings.append(f"{path}: a symlink whose target is missing")
    return findings


def control_layout(copy):
    first = skills(copy)[0]
    base = f".claude/skills/{first}"
    faults = {
        f"{base}/CONTEXT.md": "SPECIFIC file",
        f"{base}/config.json": "SPECIFIC file",
        f"{base}/installation/.install-state.json": "install-state file",
        f"{base}/temporary/zz.md": "temporary/ directory",
        ".claude/agents/zz.md": ".claude/agents/ directory",
        ".claude-plugin/plugin.json": ".claude-plugin/ directory",
        ".gitleaks.toml": "gitleaks configuration",
        "tools/.gitleaksignore": "gitleaks configuration",
        "CLAUDE.md": "a CLAUDE.md",
        f"{base}/CLAUDE.md": "a CLAUDE.md",
        "CLAUDE.local.md": "a CLAUDE.md",
        ".mcp.json": "MCP server configuration",
        ".claude/settings.local.json": "Claude Code settings file",
        SETTINGS: "not exactly the attribution-only content",
    }
    for p in faults:
        write(copy, p, "{}\n")
    links = {
        f"{base}/zz-escape": ("../../../../zz-outside", "leaves the repository"),
        f"{base}/zz-absolute": ("/etc/hostname", "absolute target"),
        f"{base}/zz-dangling": ("no-such-file", "target is missing"),
    }
    for p, (target, _) in links.items():
        os.symlink(target, copy / p)
    # decoys: fixture SPECIFIC files, a renamed fixture config, an in-repo symlink
    write(copy, f"{SPECIFIC_EXEMPT}.claude/skills/zz-decoy/CONTEXT.md", "fixture\n")
    write(copy, f"{SPECIFIC_EXEMPT}.claude/skills/zz-decoy/config.json", "{}\n")
    write(copy, f"{base}/fixtures/zz-decoy.fixture.json", "{}\n")
    os.symlink("SKILL.md", copy / f"{base}/zz-decoy-link.md")
    write(copy, f"{base}/zz-decoy-CLAUDE.md", "a file whose name only ends in CLAUDE.md\n")
    expected = list(faults.items()) + [(p, why) for p, (_, why) in links.items()]
    return expected, ["zz-decoy"]


# ------------------------------------------------------------------- ascii

def check_ascii(root):
    findings = []
    for path in prose(root):
        for no, line in enumerate(lines_of(root, path), 1):
            for col, ch in enumerate(line, 1):
                if ord(ch) > 127:
                    findings.append(f"{path}:{no}:{col}: non-ASCII U+{ord(ch):04X}; fleet prose is plain ASCII")
                    break
    return findings


def control_ascii(copy):
    first = skills(copy)[0]
    skill_md = f".claude/skills/{first}/SKILL.md"
    append(copy, skill_md, "\nAn em dash \u2014 here.\n")
    created = ["templates/zz-gate-control.md", "examples/zz-gate-control.md", "zz-gate-control.md"]
    for p in created:
        write(copy, p, "A \u201ccurly\u201d quote.\n")
    write(copy, f".claude/skills/{first}/fixtures/zz-decoy.md", "A captured \u2014 pane.\n")
    write(copy, f".claude/skills/{first}/zz-decoy.txt", "Not prose \u2014 not checked.\n")
    expected = [(skill_md, "U+2014")] + [(p, "U+201C") for p in created]
    return expected, ["zz-decoy"]


# ------------------------------------------------------------- frontmatter

KEY_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ ]+(.*?))?[ ]*$")
BLOCK = re.compile(r"[>|][+-]?")


def scalar(val, where):
    """One-line scalar: double-quoted, single-quoted or plain; anything else refused."""
    if val.startswith('"'):
        try:
            out = json.loads(val)
        except ValueError:
            raise ValueError(f"{where}: double-quoted scalar the restricted parser cannot read") from None
        if not isinstance(out, str):
            raise ValueError(f"{where}: double-quoted scalar the restricted parser cannot read")
        return out
    if val.startswith("'"):
        if len(val) < 2 or not val.endswith("'") or "'" in val[1:-1].replace("''", ""):
            raise ValueError(f"{where}: single-quoted scalar the restricted parser cannot read")
        return val[1:-1].replace("''", "'")
    if val[0] in "[]{}&*!%@`|>#,?:-" and not re.match(r"-?[0-9]", val):
        raise ValueError(f"{where}: a value starting with '{val[0]}' is outside the subset this parser reads; quote it")
    if ": " in val or val.endswith(":"):
        raise ValueError(f"{where}: plain scalar contains ': ', which YAML reads as a mapping; "
                         f"quote it or use a folded block (>)")
    if " #" in val:
        raise ValueError(f"{where}: plain scalar contains ' #', which YAML reads as a comment; quote it")
    return val


def parse_frontmatter(text):
    """The YAML subset SKILL.md frontmatter uses: top-level `key: scalar`,
    `key: >` / `|` blocks (chomping indicator allowed), and `key:` followed by
    `  - scalar` items. Anything else raises ValueError, never a guess."""
    lines = text.split("\n")
    if lines[0] != "---":
        raise ValueError("line 1: frontmatter must open with '---'")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("frontmatter is never closed by a '---' line") from None
    out, i = {}, 1
    while i < end:
        line, where = lines[i], f"line {i + 1}"
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise ValueError(f"{where}: tab in indentation")
        if not line.strip() or line.startswith("#"):
            i += 1
            continue
        m = KEY_LINE.fullmatch(line)
        if not m:
            raise ValueError(f"{where}: not a top-level 'key: value' line (an indented line here is a plain "
                             f"scalar continued, which this parser does not read; use a folded block)")
        key, val = m.group(1), m.group(2) or ""
        if key in out:
            raise ValueError(f"{where}: duplicate key '{key}'")
        i += 1
        body = []
        while i < end and (not lines[i].strip() or lines[i][0] == " "):
            body.append(lines[i])
            i += 1
        while body and not body[-1].strip():
            body.pop()
        if BLOCK.fullmatch(val):
            if not body:
                raise ValueError(f"{where}: block scalar '{key}' has no content")
            indent = len(body[0]) - len(body[0].lstrip(" "))
            if any(b.strip() and len(b) - len(b.lstrip(" ")) < indent for b in body):
                raise ValueError(f"{where}: block scalar '{key}' is less indented than its first line")
            out[key] = (" " if val[0] == ">" else "\n").join(b[indent:] for b in body).strip()
        elif val:
            if body:
                raise ValueError(f"{where}: plain scalar '{key}' continues on the next line; use a folded block (>)")
            out[key] = scalar(val, where)
        else:
            items = [re.fullmatch(r" +- (.+)", b) for b in body if b.strip()]
            if not all(items):
                raise ValueError(f"{where}: '{key}:' is followed by something other than '- item' lines "
                                 f"(a nested mapping is outside the subset)")
            out[key] = [scalar(it.group(1).strip(), where) for it in items] if items else None
    return out


def check_frontmatter(root):
    findings = []
    for path in tracked(root):
        if path.rsplit("/", 1)[-1] != "SKILL.md" or os.path.islink(root / path):
            continue
        try:
            fm = parse_frontmatter((root / path).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            findings.append(f"{path}: {e}")
            continue
        for key in ("name", "version", "description"):
            if not isinstance(fm.get(key), str) or not fm[key].strip():
                findings.append(f"{path}: frontmatter has no non-empty '{key}'")
        parts = path.split("/")
        if isinstance(fm.get("name"), str) and len(parts) >= 2 and fm["name"] != parts[-2]:
            findings.append(f"{path}: frontmatter name '{fm['name']}' is not the directory name '{parts[-2]}'")
    return findings


def control_frontmatter(copy):
    cases = {
        "zz-colon": ("name: zz-colon\nversion: 1\ndescription: Load it: when asked\n", "plain scalar contains ': '"),
        "zz-noversion": ("name: zz-noversion\ndescription: >\n  A folded block.\n", "no non-empty 'version'"),
        "zz-flow": ("name: zz-flow\nversion: 1\ndescription: {a: b}\n", "outside the subset"),
        "zz-wrapped": ("name: zz-wrapped\nversion: 1\ndescription: a plain scalar\n  wrapped onto a second line\n",
                       "continues on the next line"),
        "zz-misnamed": ("name: other\nversion: 1\ndescription: x\n", "is not the directory name"),
        "zz-unclosed": ("name: zz-unclosed\nversion: 1\ndescription: x\n", "never closed"),
    }
    expected = []
    for d, (fm, why) in cases.items():
        close = "" if d == "zz-unclosed" else "---\n"
        write(copy, f".claude/skills/{d}/SKILL.md", f"---\n{fm}{close}\n# {d}\n")
        expected.append((f".claude/skills/{d}/SKILL.md", why))
    write(copy, ".claude/skills/zz-decoy/SKILL.md",
          "---\nname: zz-decoy\nversion: 2\ndescription: >-\n  Folded: with a colon, and\n\n  a blank line.\n"
          "summary: 'Quoted: it''s fine'\ntags:\n  - one\n  - \"two: quoted\"\nrequires_install: false\n---\n")
    return expected, ["zz-decoy"]


# ---------------------------------------------------------- actions-pinned

USES = re.compile(r"""\s*(?:-\s+)?uses\s*:\s*(['"]?)([^'"\s#]+)\1\s*(?:#.*)?""")


def action_files(root):
    return [p for p in tracked(root)
            if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)
            or re.fullmatch(r"(\.github/actions/.+/)?action\.ya?ml", p)]


def check_actions_pinned(root):
    findings = []
    for path in action_files(root):
        for no, line in enumerate(lines_of(root, path), 1):
            if line.lstrip().startswith("#") or not re.search(r"(^|[\s{,-])uses\s*:", line):
                continue
            m = USES.fullmatch(line)
            ref = m.group(2) if m else None
            if ref is None:
                findings.append(f"{path}:{no}: a 'uses:' this gate cannot read; write it as one 'uses: <ref>' line")
            elif ref.startswith("./"):
                continue
            elif ref.startswith("docker://"):
                if not re.search(r"@sha256:[0-9a-f]{64}$", ref):
                    findings.append(f"{path}:{no}: '{ref}' is not pinned by a sha256 digest")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}", ref):
                findings.append(f"{path}:{no}: '{ref}' is not pinned by a full 40-hex commit SHA")
    return findings


def control_actions_pinned(copy):
    ci = ".github/workflows/ci.yml"
    append(copy, ci, "\n  zz-control:\n    runs-on: ubuntu-24.04\n    steps:\n"
                     "      - uses: actions/checkout@v4\n"
                     "      - uses: ./.github/actions/zz-decoy-local\n"
                     "      - uses: actions/setup-node@0123456789abcdef0123456789abcdef01234567 # zz-decoy\n")
    write(copy, ".github/workflows/zz-control.yaml",
          "on: push\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n"
          "      - uses: \"docker://alpine:3\"\n      - {uses: actions/cache@v4}\n")
    n = next(i for i, l in enumerate(lines_of(copy, ci), 1) if l.endswith("actions/checkout@v4"))
    expected = [(f"{ci}:{n}", "actions/checkout@v4"),
                (".github/workflows/zz-control.yaml:6", "docker://alpine:3"),
                (".github/workflows/zz-control.yaml:7", "cannot read")]
    return expected, ["zz-decoy", "0123456789abcdef0123456789abcdef01234567"]


# --------------------------------------------------------- workflow-safety

# CI runs on the repository owner's self-hosted runners, so every job is code
# running on the owner's machine. Each rule below is a gate rather than a
# comment because the workflow keeps running, and keeps passing, without it:
#   * FORK_GATE on every job, as exact text. A job without it runs the code of a
#     fork's pull request on the owner's machine (the repository's approval of
#     outside contributors' runs is the second lock, not the first). A reworded
#     condition that lets a fork through reads like one that does not.
#   * TRIGGERS. The gate's first clause passes every event that is not
#     pull_request: pull_request_target, issue_comment, workflow_run and the like
#     are events someone else can raise, so these three are the only triggers.
#   * SELF_HOSTED. A job on a GitHub-hosted label queues on runners this
#     repository does not use, and one on another self-hosted label lands on a
#     machine whose contract (CONTRIBUTING.md section 9) nobody checked.
#   * permissions contents: read at the top and in no job: a job's own
#     permissions block replaces the workflow's, so a write token comes back
#     through it.
#   * No `secrets` on any line that is not a comment: no secret exists for these
#     runners, and a reference is the first step towards one.
FORK_GATE = ("github.event_name != 'pull_request' || "
             "github.event.pull_request.head.repo.full_name == github.repository")
SELF_HOSTED = (["self-hosted", "Linux", "X64", "agent-fleet-linux"],
               ["self-hosted", "macOS", "ARM64", "agent-fleet-mac"])
TRIGGERS = ("push", "pull_request", "workflow_dispatch")
WF_KEY = re.compile(r"""(?P<k>[A-Za-z0-9_.-]+|"[^"]*"|'[^']*')\s*:(?:\s+(?P<v>.*?))?\s*""")


def workflows(root):
    """The files GitHub reads as workflows: .github/workflows/*.yml|yaml, no subdirectory."""
    return [p for p in tracked(root) if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)]


def wf_lines(lines):
    """(line number, indent, text) of every line that carries YAML: blank lines,
    comment-only lines and document markers dropped."""
    out = []
    for no, line in enumerate(lines, 1):
        text = line.strip()
        if text and not text.startswith("#") and text not in ("---", "..."):
            out.append((no, len(line) - len(line.lstrip(" ")), text))
    return out


def wf_mapping(items, where):
    """{key: (line number, inline value, body items)} of the block mapping whose
    keys sit at the first item's indent. A `- ` line at the keys' own indent is
    part of the key above it (a sequence written at its parent's indent). A
    trailing ` # comment` is dropped from a value. Anything else is ValueError,
    never a guess."""
    out, key = {}, None
    ind = items[0][1] if items else 0
    for no, i, text in items:
        if i < ind:
            raise ValueError(f"{where}:{no}: less indented than the mapping it belongs to")
        if i == ind and not text.startswith("-"):
            m = WF_KEY.fullmatch(text)
            if not m:
                raise ValueError(f"{where}:{no}: not a 'key: value' line this gate can read")
            key = m.group("k").strip("\"'")
            if key in out:
                raise ValueError(f"{where}:{no}: duplicate key '{key}'")
            out[key] = (no, re.sub(r"\s+#.*$", "", m.group("v") or ""), [])
        elif key is None:
            raise ValueError(f"{where}:{no}: content before the first key of its mapping")
        else:
            out[key][2].append((no, i, text))
    return out


def wf_list(value, body):
    """A scalar, a one-line [flow, list] or a block list of scalars, as a list of
    strings; None for any other form."""
    if value:
        m = re.fullmatch(r"\[(.*)\]", value)
        return [x.strip().strip("\"'") for x in (m.group(1).split(",") if m else [value]) if x.strip()]
    if body and all(i == body[0][1] and t.startswith("- ") for _, i, t in body):
        return [t[2:].strip().strip("\"'") for _, _, t in body]
    return None


def wf_triggers(value, body, where):
    if value or (body and body[0][2].startswith("-")):
        return wf_list(value, body) or [f"<unreadable: {value}>"]
    return list(wf_mapping(body, where))


def wf_permissions(value, body, where):
    """A permissions value as a {scope: access} dict, or its raw text (read-all, ...)."""
    m = re.fullmatch(r"\{(.*)\}", value)
    if m:
        pairs = [p.split(":", 1) for p in m.group(1).split(",") if p.strip()]
        return {k.strip(): v.strip() for k, v in pairs} if all(len(p) == 2 for p in pairs) else value
    if value:
        return value
    return {k: v for k, (_, v, _) in wf_mapping(body, where).items()}


def check_workflow_safety(root):
    findings = []
    for path in workflows(root):
        lines = lines_of(root, path)
        findings += [f"{path}:{no}: names `secrets`; no secret exists for these runners, and no job may reference one"
                     for no, line in enumerate(lines, 1)
                     if not line.lstrip().startswith("#") and re.search(r"\bsecrets\b", line)]
        try:
            findings += workflow_findings(path, wf_mapping(wf_lines(lines), path))
        except ValueError as e:
            findings.append(f"{e}; the gate cannot check what it cannot read")
    return findings


def workflow_findings(path, top):
    out = []
    on = top.get("on") or top.get("true")  # YAML 1.1 reads a bare `on` key as true
    if on is None:
        out.append(f"{path}: no 'on:' key, so its triggers cannot be checked")
    else:
        extra = [t for t in wf_triggers(on[1], on[2], path) if t not in TRIGGERS]
        if extra:
            out.append(f"{path}:{on[0]}: trigger(s) {', '.join(extra)}; only {', '.join(TRIGGERS)} may start "
                       f"a job on the owner's runners")
    perm = top.get("permissions")
    if perm is None or wf_permissions(perm[1], perm[2], path) != {"contents": "read"}:
        out.append(f"{path}:{perm[0] if perm else 1}: workflow permissions are not exactly contents: read")
    jobs = wf_mapping(top["jobs"][2], path) if "jobs" in top else {}
    if not jobs:
        out.append(f"{path}: no job found under 'jobs:'")
    for job, (no, _, body) in jobs.items():
        keys = wf_mapping(body, path)
        gate = keys.get("if")
        if gate is None:
            out.append(f"{path}:{no}: job '{job}' carries no fork gate `if:`; it would run a fork's pull request "
                       f"on the owner's machine")
        elif gate[1] != FORK_GATE:
            out.append(f"{path}:{gate[0]}: job '{job}' has an `if:` that is not the exact fork gate: {FORK_GATE}")
        runs = keys.get("runs-on")
        labels = wf_list(runs[1], runs[2]) if runs else None
        if labels not in SELF_HOSTED:
            out.append(f"{path}:{runs[0] if runs else no}: job '{job}' runs on {labels}, not one of the "
                       f"self-hosted label sets {list(SELF_HOSTED)}")
        if "permissions" in keys:
            out.append(f"{path}:{keys['permissions'][0]}: job '{job}' sets its own permissions, which replace "
                       f"the workflow's contents: read")
    return out


def control_workflow_safety(copy):
    # Every real workflow gets a planted job inserted right under its `jobs:` line,
    # so the faults never depend on the real jobs being right: on a tree whose own
    # jobs lack the gate, the control still fires and the verdict is FAIL with
    # findings, never NO VERDICT.
    real = workflows(copy)
    if not real:
        raise NoVerdict("no workflow under .github/workflows/ to plant a fault in")
    expected = []
    for path in real:
        lines = lines_of(copy, path)
        try:
            top = wf_mapping(wf_lines(lines), path)
            jobs_no, (_, indent, _) = top["jobs"][0], top["jobs"][2][0]
        except (ValueError, KeyError, IndexError) as e:
            raise NoVerdict(f"cannot find the jobs of {path} to plant a job among: {e!r}") from None
        pad = " " * indent
        lines[jobs_no:jobs_no] = [f"{pad}zz-planted:", f"{pad}  runs-on: ubuntu-latest", f"{pad}  steps:",
                                  f"{pad}    - run: echo planted"]
        write(copy, path, "\n".join(lines))
        expected += [(path, "job 'zz-planted' carries no fork gate"),
                     (path, "job 'zz-planted' runs on ['ubuntu-latest']")]
    write(copy, ".github/workflows/zz-control.yml",
          "on:\n  push:\n  pull_request_target:\npermissions: write-all\njobs:\n  near:\n"
          "    if: github.event.pull_request.head.repo.fork == false\n"
          "    runs-on: [self-hosted, Linux, X64, agent-fleet-linux]\n"
          "    permissions:\n      contents: write\n"
          "    steps:\n      - run: echo \"$T\"\n        env:\n          T: ${{ secrets.ZZ_TOKEN }}\n")
    write(copy, ".github/workflows/zz-control-perm.yaml",
          "on: [push]\npermissions:\n  contents: read\n  pull-requests: write\njobs:\n  a:\n"
          f"    if: {FORK_GATE}\n    runs-on: [self-hosted, Linux, X64, agent-fleet-linux]\n    steps:\n"
          "      - run: echo a\n")
    zz = ".github/workflows/zz-control.yml"
    expected += [(zz, "trigger(s) pull_request_target"), (zz, "not exactly contents: read"),
                 (zz, "job 'near' has an `if:` that is not the exact fork gate"),
                 (zz, "job 'near' sets its own permissions"), (zz, "names `secrets`"),
                 (".github/workflows/zz-control-perm.yaml", "not exactly contents: read")]
    # decoys: every rule holds, in the other forms the gate reads; comments, a step's
    # if and a run block may say anything; a subdirectory is not a workflow to GitHub
    write(copy, ".github/workflows/zz-decoy.yaml",
          "# secrets.ZZ in a comment; runs-on: ubuntu-latest in a comment\n---\n"
          "\"on\": [push, workflow_dispatch]\npermissions: {contents: read}\njobs:\n  zz-decoy-job:\n"
          f"    if: {FORK_GATE}  # a trailing comment\n"
          "    runs-on:\n      - self-hosted\n      - macOS\n      - ARM64\n      - agent-fleet-mac\n"
          "    steps:\n    - name: a step\n      if: always()\n      run: |\n"
          "        # secrets.ZZ in a shell comment\n        echo \"runs-on: ubuntu-latest\"\n        echo \"if: false\"\n")
    write(copy, ".github/workflows/zz-decoy/nested.yml", "on: issue_comment\njobs:\n  a:\n    runs-on: ubuntu-latest\n")
    return expected, ["zz-decoy"]


# --------------------------------------------------------- setup-checklist

def leaves(obj, pre=()):
    """Key paths of a config example, `_`-keys dropped; a list of objects is `key[]`."""
    if isinstance(obj, dict):
        keys = [k for k in obj if not k.startswith("_")]
        if not keys:
            yield pre
        for k in keys:
            yield from leaves(obj[k], pre + (k,))
    elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        seen = []
        for x in obj:
            if not [k for k in x if not k.startswith("_")]:
                continue
            for leaf in leaves(x, pre[:-1] + (pre[-1] + "[]",)):
                if leaf not in seen:
                    seen.append(leaf)
        yield from seen or [pre]
    else:
        yield pre


def example_keys(path, fold_conventions=False):
    keys = []
    for leaf in leaves(json.loads(path.read_text(encoding="utf-8"))):
        if fold_conventions and leaf[:1] == ("conventions",):
            leaf = leaf[:2]  # a conventions value is an object by contract (CONVENTIONS.md)
        if leaf not in keys:
            keys.append(leaf)
    return keys


def matches(token, leaf):
    """A checklist token covers a key path; a <placeholder> segment matches any one key."""
    segs = tuple(token.split("."))
    return len(segs) == len(leaf) and all(s == k or re.fullmatch(r"<[^<>]+>", s) for s, k in zip(segs, leaf))


def checklist_items(section, heading):
    """The checklist items under the bold heading starting with `heading`."""
    out, cur, on = [], None, False
    for line in section:
        if line.startswith("**"):
            on = line.startswith(heading)
            cur = None
            continue
        if not on:
            continue
        if line.startswith("- [ ]"):
            cur = [line[5:]]
            out.append(cur)
        elif cur is not None and line.startswith("  ") and line.strip():
            cur.append(line)
        else:
            cur = None
    return [" ".join(x) for x in out]


def compare(where, tokens, keys):
    findings = [f"SETUP.md: closing checklist misses {where} key `{'.'.join(k)}`"
                for k in keys if not any(matches(t, k) for t in tokens)]
    findings += [f"SETUP.md: closing checklist lists `{t}`, which {where} does not carry"
                 for t in tokens if not any(matches(t, k) for k in keys)]
    return findings


def check_setup_checklist(root):
    lines = (root / "SETUP.md").read_text(encoding="utf-8").split("\n")
    try:
        start = lines.index("## Closing checklist")
    except ValueError:
        return ["SETUP.md: no '## Closing checklist' section"]
    section = lines[start + 1:]
    section = section[:next((i for i, l in enumerate(section) if l.startswith("## ")), len(section))]
    findings = []
    manifest = checklist_items(section, "**`.claude/fleet.json`**")
    if not manifest:
        findings.append("SETUP.md: closing checklist has no items under **`.claude/fleet.json`**")
    tokens = [t for item in manifest for t in re.findall(r"`([^`]+)`", item)]
    findings += compare("templates/fleet.example.json", tokens,
                        example_keys(root / "templates/fleet.example.json", fold_conventions=True))
    rows = {}
    for item in checklist_items(section, "**Each skill's `config.json`**"):
        toks = re.findall(r"`([^`]+)`", item)
        if toks:
            rows[toks[0]] = toks[1:]
    examples = {p.split("/")[2]: root / p for p in tracked(root)
                if re.fullmatch(r"\.claude/skills/[^/]+/config\.example\.json", p)}
    for skill, path in sorted(examples.items()):
        if skill not in rows:
            findings.append(f"SETUP.md: closing checklist has no row for `{skill}`, which ships config.example.json")
            continue
        findings += compare(f".claude/skills/{skill}/config.example.json", rows[skill], example_keys(path))
    for skill, toks in rows.items():
        if skill not in examples and toks:
            findings.append(f"SETUP.md: closing checklist lists keys for `{skill}`, which ships no config.example.json")
    return findings + check_unit_placeholders(root, section)


# A unit template's placeholder: <word>, where a word may hold hyphens and
# spaces (`<state dir>`). A comma or other punctuation ends it, so prose in a
# comment such as `<this file, rendered>` is not read as a value to fill.
UNIT_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 -]*>")
# Unit templates: a systemd unit, and its launchd form, a plist.
UNIT_TEMPLATE = r"[^`]+\.(?:service|plist)\.example"


def unit_placeholders(text):
    """The template's placeholders, in order. A token whose closing tag is in the
    file too (`<key>` beside `</key>`) is an XML element of a plist; a
    placeholder never has one."""
    return [t for t in dict.fromkeys(UNIT_PLACEHOLDER.findall(text)) if f"</{t[1:]}" not in text]


def check_unit_placeholders(root, section):
    """Each tracked unit template has a checklist heading naming its path in
    backticks; the items under it name every <placeholder> in the template, and
    every token they name occurs in the template. The second half is what holds
    a sed-filled template whose tokens carry no angle brackets: its list cannot
    be derived from the file, but a token the file no longer carries is stale."""
    findings, headed = [], {}
    for line in section:
        if line.startswith("**"):
            for path in re.findall(f"`({UNIT_TEMPLATE})`", line):
                headed[path] = [t for item in checklist_items(section, line)
                                for t in re.findall(r"`([^`]+)`", item)]
    units = [p for p in tracked(root) if re.fullmatch(UNIT_TEMPLATE, p)]
    for path in units:
        if path not in headed:
            findings.append(f"SETUP.md: closing checklist has no heading for unit template `{path}`")
            continue
        if not headed[path]:
            # Both halves below pass vacuously on an empty list, and a sed-filled
            # template's tokens cannot be derived from the file to fill it.
            findings.append(f"SETUP.md: closing checklist heading for unit template `{path}` lists no token")
            continue
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        want = unit_placeholders(text)
        findings += [f"SETUP.md: closing checklist misses placeholder `{w}` of {path}"
                     for w in want if w not in headed[path]]
        findings += [f"SETUP.md: closing checklist lists `{t}` for {path}, which that template does not carry"
                     for t in headed[path] if t not in text]
    findings += [f"SETUP.md: closing checklist heading names `{p}`, which is not a tracked unit template"
                 for p in headed if p not in units]
    return findings


def control_setup_checklist(copy):
    fleet = copy / "templates/fleet.example.json"
    data = json.loads(fleet.read_text(encoding="utf-8"))
    data["zz_manifest_key"] = 1
    fleet.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    write(copy, ".claude/skills/zz-row/config.example.json",
          '{"_comment": "c", "a": 1, "nested": {"_comment": "c", "b": 2}, "zz_added": {"key": "x"}}\n')
    write(copy, ".claude/skills/zz-new/config.example.json", '{"a": 1}\n')
    write(copy, ".claude/skills/zz-decoy/config.example.json",
          '{"users": {"id-ada": "Ada", "id-grace": "Grace"}, '
          '"list": [{"_comment": "c"}, {"name": "n"}], "empty": []}\n')
    lines = (copy / "SETUP.md").read_text(encoding="utf-8").split("\n")
    for heading, rows in (("**`.claude/fleet.json`**", ["- [ ] `zz_stale_row`"]),
                          ("**Each skill's `config.json`**",
                           ["- [ ] `zz-row` - `a`, `nested.b`, `zz_gone`",
                            "- [ ] `zz-decoy` - `users.<user-id>`, `list[].name`,",
                            "      `empty`",
                            "- [ ] `zz-noexample` - `x`"])):
        at = next(i for i, line in enumerate(lines) if line.startswith(heading)) + 1
        lines[at:at] = rows
    # Unit templates: a placeholder planted in a REAL template of each kind (the
    # region the gate reads; in a plist, inside its dict as a real one sits), a
    # stale token, a template of each kind with no heading, a heading naming no
    # template, and decoys whose tokens are all listed and present: a sed-style
    # token, comment prose that is not a placeholder, and a plist's own
    # elements (<key>, <string>, <integer>, <dict>), which are not placeholders.
    for kind in ("service", "plist"):
        if not any(p.endswith(f".{kind}.example") for p in tracked(copy)):
            raise NoVerdict(f"no tracked *.{kind}.example to plant a placeholder in")
    real = sorted(p for p in tracked(copy) if p.endswith(".service.example"))
    append(copy, real[0], "\n# <zz-new-placeholder>\n")
    plist = sorted(p for p in tracked(copy) if p.endswith(".plist.example"))[0]
    text = (copy / plist).read_text(encoding="utf-8")
    if not any(line.startswith("**") and f"`{plist}`" in line for line in lines):
        # The planted placeholder must meet a heading, or it reads as "no heading".
        at = lines.index("## Closing checklist") + 1
        lines[at:at] = ["", f"**zz real job**, from `{plist}`:", "",
                        "- [ ] " + ", ".join(f"`{t}`" for t in unit_placeholders(text)), ""]
    at_dict = text.rindex("</dict>")
    write(copy, plist, text[:at_dict] + "  <key>ZZ</key>\n  <string><zz-plist-placeholder></string>\n"
          + text[at_dict:])
    write(copy, ".claude/skills/zz-stale/installation/zz-stale.service.example", "User=<zz-s>\n")
    write(copy, ".claude/skills/zz-unit/installation/zz.service.example", "User=<zz-x>\n")
    write(copy, ".claude/skills/zz-unit/installation/zz.plist.example",
          "<plist version=\"1.0\">\n<dict>\n  <key>UserName</key>\n  <string><zz-y></string>\n</dict>\n</plist>\n")
    write(copy, ".claude/skills/zz-empty/installation/zz-empty.service.example", "User=ZZ_SED_TOKEN\n")
    write(copy, ".claude/skills/zz-decoy/installation/zz-decoy.service.example",
          "User=ZZ_DECOY_TOKEN\nGroup=<zz-decoy-ph>\n# <a comment, not a placeholder>\n")
    write(copy, ".claude/skills/zz-decoy/installation/zz-decoy.plist.example",
          "<plist version=\"1.0\">\n<!-- <a comment, not a placeholder> -->\n<dict>\n"
          "  <key>Label</key>\n  <string><zz-decoy-pl>.job</string>\n"
          "  <key>ThrottleInterval</key>\n  <integer>10</integer>\n  <key>RunAtLoad</key>\n  <true/>\n"
          "</dict>\n</plist>\n")
    at = lines.index("## Closing checklist") + 1
    lines[at:at] = ["",
                    "**zz stale unit**, from `.claude/skills/zz-stale/installation/zz-stale.service.example`:",
                    "", "- [ ] `<zz-s>`, `<zz-gone>`", "",
                    "**zz missing unit**, from `zz/missing.service.example`:", "", "- [ ] `X`", "",
                    "**zz empty unit**, from `.claude/skills/zz-empty/installation/zz-empty.service.example`:",
                    "",
                    "**zz decoy unit**, from `.claude/skills/zz-decoy/installation/zz-decoy.service.example`:",
                    "", "- [ ] `ZZ_DECOY_TOKEN`, `<zz-decoy-ph>`", "",
                    "**zz decoy job**, from `.claude/skills/zz-decoy/installation/zz-decoy.plist.example`:",
                    "", "- [ ] `<zz-decoy-pl>`", ""]
    (copy / "SETUP.md").write_text("\n".join(lines), encoding="utf-8")
    expected = [("SETUP.md", "fleet.example.json key `zz_manifest_key`"),
                ("SETUP.md", "lists `zz_stale_row`"),
                ("SETUP.md", "zz-row/config.example.json key `zz_added.key`"),
                ("SETUP.md", "lists `zz_gone`, which .claude/skills/zz-row/config.example.json"),
                ("SETUP.md", "no row for `zz-new`"),
                ("SETUP.md", "lists keys for `zz-noexample`"),
                ("SETUP.md", f"misses placeholder `<zz-new-placeholder>` of {real[0]}"),
                ("SETUP.md", f"misses placeholder `<zz-plist-placeholder>` of {plist}"),
                ("SETUP.md", "lists `<zz-gone>` for .claude/skills/zz-stale/"),
                ("SETUP.md", "no heading for unit template `.claude/skills/zz-unit/installation/zz.service.example`"),
                ("SETUP.md", "no heading for unit template `.claude/skills/zz-unit/installation/zz.plist.example`"),
                ("SETUP.md", "names `zz/missing.service.example`, which is not a tracked unit template"),
                ("SETUP.md", "zz-empty.service.example` lists no token")]
    return expected, ["zz-decoy"]


# ---------------------------------------------------------- portable-shell

# What a fleet host's shell may not use: a macOS host has /bin/bash 3.2 and BSD
# userland, a Linux host bash 5 and GNU. Each row: the construct's name, its
# pattern over a command line's code (the comment cut off), the portable form,
# and the BSD fallback that makes the GNU form portable when the same command
# line carries it (`stat -c ... || stat -f ...`), or None.
# CMD is a command position: a line start, after ; & | ( ) { or a backquote
# (`)` for a case arm, `{` for a brace group but not `${`), after $(, after an
# opening quote (one that follows a space, = or ( : a command in a string
# handed to bash -c or ssh), or after a word that runs the next one; then any
# VAR=value assignments.
CMD = (r"(?:^|[;&|()`]|(?<!\$)\{|\$\(|(?:^|(?<=[\s=(]))['\"]|(?<![\w-])(?:then|do|else|elif|if|while|"
       r"until|exec|nohup|sudo|command|env|time|xargs|!)\s)\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*")
OPTS = r"\s+(?:-[A-Za-z]+\s+)*"  # option clusters before the one that matters
SHELL_RULES = [
    ("grep -P", CMD + r"[ef]?grep" + OPTS + r"(?:-[A-Za-z]*P|--perl-regexp\b)",
     "BSD grep has no PCRE: grep -E, or sed -n", None),
    ("stat -c", CMD + r"stat" + OPTS + r"(?:-[A-Za-z]*c|--format\b|--printf\b)",
     "BSD stat formats with -f: stat -c ... || stat -f ..., or python3", CMD + r"stat" + OPTS + r"-[A-Za-z]*f"),
    ("sed -i", CMD + r"sed" + OPTS + r"(?:-[A-Za-z]*i|--in-place\b)",
     "BSD sed -i needs a suffix argument: write a temporary file and mv it", None),
    ("date -d", CMD + r"date" + OPTS + r"(?:-[A-Za-z]*d|--date\b)",
     "BSD date parses with -j -f: date -d ... || date -j -f ..., or python3", CMD + r"date" + OPTS + r"-[A-Za-z]*j"),
    ("find -printf", CMD + r"find\b[^;|&]*?\s-f?printf\b",
     "BSD find has no -printf: -print0 piped to a reader, or python3", None),
    ("timeout as a command", CMD + r"timeout\b(?!\s*[=(])",
     "macOS has no timeout(1): a python3 helper that kills the process group", None),
    ("setsid as a command", CMD + r"setsid\b(?!\s*[=(])",
     "macOS has no setsid(1): nohup ... &, or python3's os.setsid", None),
    ("flock as a command", CMD + r"flock\b(?!\s*[=(])",
     "macOS has no flock(1): mkdir as the lock, or python3's fcntl", None),
    ("declare -A", r"(?<![\w-])(?:declare|typeset|local)" + OPTS + r"-[A-Za-z]*A",
     "bash 3.2 has no associative array: an indexed array, or a file", None),
    ("mapfile", CMD + r"mapfile\b", "bash 3.2 has no mapfile: a while read loop", None),
    ("readarray", CMD + r"readarray\b", "bash 3.2 has no readarray: a while read loop", None),
    ("case modification ${x,,} ${x^^}", r"\$\{[#!]?(?:[A-Za-z_]\w*|[0-9]+|[@*])(?:\[[^]]*\])?(?:\^|,)",
     "bash 3.2 has no case modification: tr '[:upper:]' '[:lower:]'", None),
    ("|&", r"(?<!\|)\|&", "bash 3.2 has no |&: 2>&1 |", None),
    ("&>>", r"&>>", "bash 3.2 has no &>>: >> file 2>&1", None),
    # An apostrophe in the word of ${x:-word} (any of :- - :+ + := = :? ?) inside
    # double quotes: bash 3.2, in every mode and so as macOS's /bin/sh, opens a
    # single-quoted string there and the whole FILE fails to parse ("unexpected
    # EOF while looking for matching `''"), so not one line of it runs. dash and
    # bash 5 --posix accept it, which is why a Linux run of the script cannot see
    # it. The pattern walks the line's quoting from its start (unquoted text, an
    # escape, a whole '...', a whole "...") to an opening double quote, then
    # within that string to the ${name<op> whose word holds the apostrophe; the
    # name may be positional (${1:-...}, a function's default), special, an array
    # element or an indirection, all of which bash 3.2 refuses alike.
    ("' in a double-quoted ${x:-word}",
     r"^(?:[^\"'\\]|\\.|'[^']*'|\"(?:[^\"\\]|\\.)*\")*\"(?:[^\"\\]|\\.)*?"
     r"\$\{!?(?:[A-Za-z_]\w*|[0-9]+|[@*])(?:\[[^]]*\])?:?[-+=?][^}\"]*'",
     "bash 3.2 opens a quoted string at that apostrophe and the file does not parse: reword the default, "
     "or set it in a variable first", None),
]
SHELL_RULES = [(name, re.compile(pat), fix, unless and re.compile(unless))
               for name, pat, fix, unless in SHELL_RULES]
LINUX_ONLY = re.compile(r"#\s*linux-only:(.*)")
FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})\s*([^`\s]*)(.*)")  # indented too: a fence inside a list item
SHELL_INFO = ("bash", "sh", "shell", "zsh")
SH_SHEBANG = re.compile(r"#!.*\b(?:ba|z)?sh(\s|$)")


def code_part(line):
    """The line up to its shell comment: a # that starts a word, outside quotes."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\":
            i += 1
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t;&|("):
            return line[:i]
        i += 1
    return line


def shell_lines(root):
    """(path, line number, line) of every line the gate reads as shell: each line
    of a tracked shell script (*.sh, *.bash, or an extensionless file whose
    shebang names sh, bash or zsh), and each line inside a ```bash, ```sh,
    ```shell or ```zsh fence of a tracked Markdown file, outside fixtures/."""
    for path in tracked(root):
        full = root / path
        if os.path.islink(full) or not full.is_file() or "fixtures" in path.split("/")[:-1]:
            continue
        name = path.rsplit("/", 1)[-1]
        if name.endswith(".md"):
            fence, shell = None, False  # the open fence's marker, and whether it is shell
            for no, line in enumerate(lines_of(root, path), 1):
                m = FENCE.match(line)
                if fence is None:
                    if m:
                        fence, shell = m.group(1), m.group(2) in SHELL_INFO
                elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                        and not (m.group(2) + m.group(3)).strip():
                    fence = None  # a closing fence: the same character, as long or longer, bare
                elif shell:
                    yield path, no, line
            continue
        lines = lines_of(root, path)
        if name.endswith((".sh", ".bash")) or ("." not in name and SH_SHEBANG.match(lines[0])):
            for no, line in enumerate(lines, 1):
                yield path, no, line


def logical_lines(root):
    """(path, first line number, text) of each shell command line: physical lines
    joined across a trailing backslash, which is removed, as the shell does. A
    mark on the command's last line therefore covers all of it."""
    cur = None  # [path, first line, last line, text]
    for path, no, line in shell_lines(root):
        if cur and (cur[0] != path or cur[2] != no - 1):
            yield cur[0], cur[1], cur[3]
            cur = None
        body = line[:-1] if line.endswith("\\") else line
        cur = [path, cur[1], no, cur[3] + body] if cur else [path, no, no, body]
        if not line.endswith("\\"):
            yield cur[0], cur[1], cur[3]
            cur = None
    if cur:
        yield cur[0], cur[1], cur[3]


def check_portable_shell(root):
    findings = []
    for path, no, line in logical_lines(root):
        mark = LINUX_ONLY.search(line)
        if mark:
            if not re.search(r"\w", mark.group(1)):
                findings.append(f"{path}:{no}: a '# linux-only:' mark with no reason; name why the line "
                                f"runs only on Linux")
            continue
        code = code_part(line)
        for name, pattern, fix, unless in SHELL_RULES:
            if pattern.search(code) and not (unless and unless.search(code)):
                findings.append(f"{path}:{no}: {name} does not run on a macOS host ({fix}); "
                                f"or mark the line '# linux-only: <reason>'")
    return findings


def control_portable_shell(copy):
    planted = ["x=$(echo ab | grep -oP 'a\\Kb')", "m=$(stat -c %a f)", "sed -i 's/a/b/' f",
               "d=$(date -d @0 +%F)", "find . -type f -printf '%p\\n'", "timeout 5 sleep 9",
               "if setsid true; then :; fi", "flock -n 9", "declare -A seen", "mapfile -t a < f",
               "cat f | readarray -t a", "echo \"${name,,}\"", "echo \"${name^^}\"", "make |& tee log",
               "make &>> log", "ssh host 'stat -c %a f'", "sed -E \\\n  -i 's/a/b/' f",
               "ssh host 'cd /tmp && \\\n  timeout 9 sleep 1'", "lock() { flock -n 9; }",
               "case $x in a) timeout 5 sleep 9 ;; esac",
               # a real line from install-agent-fleet's bootstrap-target.sh, verbatim:
               # macOS's /bin/sh refuses it, so the rule is held to the case it is for.
               '    [ -s "$src" ] || { echo "FAILED: no key in ${src:-the administrator\'s home} to give $ME; '
               'install one in $U_HOME/.ssh/authorized_keys by hand" >&2; exit 1; }',
               "v=$(printf '%s' \"x ${y+it's set}\")", "f() { echo \"${1:-the agent's home}\"; }"]
    names = ["grep -P", "stat -c", "sed -i", "date -d", "find -printf", "timeout as", "setsid as",
             "flock as", "declare -A", "mapfile", "readarray", "case modification", "case modification",
             "|&", "&>>", "stat -c", "sed -i", "timeout as", "flock as", "timeout as",
             "' in a double-quoted", "' in a double-quoted", "' in a double-quoted"]
    first = skills(copy)[0]
    scripts = sorted(p for p in tracked(copy) if p.endswith(".sh") and "fixtures" not in p.split("/"))
    if not scripts:
        raise NoVerdict("no tracked *.sh to plant a construct in")
    expected = []

    def plant(path, lines_before, wrap=None):
        """Append the planted lines (a new file when absent); expect each at the
        number of its FIRST physical line."""
        n = len(lines_of(copy, path)) if (copy / path).exists() else 0
        body = "\n".join(wrap(planted) if wrap else planted)
        if n:
            append(copy, path, "\n" + body + "\n")
        else:
            write(copy, path, body + "\n")
        at = (n + 1 if n else 1) + lines_before
        for item, name in zip(planted, names):
            expected.append((f"{path}:{at}", name))
            at += item.count("\n") + 1

    plant(scripts[0], 0)
    plant(f".claude/skills/{first}/zz-gate-control", 1, lambda ls: ["#!/usr/bin/env bash", *ls])
    plant("README.md", 1, lambda ls: ["```bash", *ls, "```"])
    plant(f".claude/skills/{first}/zz-gate-control.md", 2, lambda ls: ["Run:", "~~~sh run-me", *ls, "~~~"])
    write(copy, "zz-gate-control.sh", "#!/bin/sh\nsed -i 's/a/b/' f   # linux-only:\n")
    expected.append(("zz-gate-control.sh:2", "mark with no reason"))
    # decoys: portable forms, words that only look like the commands, comments,
    # a marked line, a shell construct outside a shell fence or file
    write(copy, f".claude/skills/{first}/zz-decoy.sh", "\n".join([
        "#!/usr/bin/env bash", "x=$(grep -E 'a\\b' f)", "stat -f %Lp f", "sed -n p f", "sed -e 's/i/j/' f",
        "date -u +%s", "find . -type f -print0", "timeout=5", "local timeout", "echo \"$timeout\"",
        "run --timeout 3", "timeout() { python3 t.py \"$@\"; }", "declare -a arr", "echo \"${x:-a,b}\" \"${#x}\"",
        "a || b", "make &> /dev/null", "make >> log 2>&1", "pgrep -P 1", "# grep -P in a comment",
        "echo 'a' # stat -c in a trailing comment", "sed -i 's/a/b/' f   # linux-only: a GNU sed on Linux CI",
        "echo \"${x}\" ${#} \"$#\"", "python3 \"$root/tests/runner.py\" timeout 900 -- bash t.sh",
        "setsid nohup env A=1 \\", "  node x.mjs > log 2>&1 &   # linux-only: macOS starts this line at nohup",
        "mode() { stat -c %a \"$1\" 2>/dev/null || stat -f %Lp \"$1\"; }", "echo \"${timeout}\" \"${flock:-x}\"",
        "d=$(date -d @0 +%F 2>/dev/null || date -j -r 0 +%F)",
        "echo \"it's ${x:-a}\" \"${y:-b} it's\" \"${z}'s\" \"${#x}'s\"", "echo '${x:-it'\"'\"'s}'",
        "echo \"${x:-a}\" 'it'\\''s ${y:-b}'"])
        + "\n")
    write(copy, f".claude/skills/{first}/zz-decoy.md", "\n".join([
        "Prose may say sed -i and grep -P.", "```python", "subprocess.run(['grep', '-P', 'x'])", "```",
        "```text", "timeout 5 sleep 9", "```", "````markdown", "```bash", "inside a markdown fence: flock 9",
        "```", "````"]) + "\n")
    write(copy, f".claude/skills/{first}/zz-decoy.py", "import os\nos.system('sed -i s/a/b/ f')\n")
    write(copy, f".claude/skills/{first}/fixtures/zz-decoy.sh", "sed -i 's/a/b/' f\n")
    return expected, ["zz-decoy"]


# ------------------------------------------------------- starter-knowledge

STARTER = "examples/knowledge-base"


def check_starter_knowledge(root):
    lessons = [p for p in tracked(root) if p.startswith(STARTER + "/") and p.endswith(".md")
               and p.rsplit("/", 1)[-1] != "index.md"]
    if not lessons:
        return [f"{STARTER}: no starter lesson"]
    findings = [f"{p}:1: a starter lesson whose first line is not the '> EXAMPLE lesson - ' marker"
                for p in lessons if not lines_of(root, p)[0].startswith("> EXAMPLE lesson - ")]
    checker = root / ".claude/skills/knowledge-base/check_indexes.py"
    r = subprocess.run([sys.executable, str(checker), str(root / STARTER)], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise NoVerdict(f"check_indexes.py exited {r.returncode}: {(r.stderr or r.stdout).strip()}")
    if r.returncode == 1:
        problems = [l.strip() for l in r.stdout.split("\n") if l.startswith("  ")]
        findings += [f"{STARTER}: {p}" for p in problems] or [f"{STARTER}: check_indexes.py exited 1"]
    return findings


def control_starter_knowledge(copy):
    marker = lines_of(copy, sorted(p for p in tracked(copy) if p.startswith(STARTER + "/")
                                   and p.rsplit("/", 1)[-1] != "index.md")[0])[0]
    write(copy, f"{STARTER}/zz-orphan.md", f"{marker}\n\n# Not indexed\n")
    write(copy, f"{STARTER}/zz-unmarked.md", "# A lesson with no marker\n")
    append(copy, f"{STARTER}/index.md", "\n- [Unmarked](zz-unmarked.md) - control\n")
    expected = [(STARTER, "does not link zz-orphan.md"), (f"{STARTER}/zz-unmarked.md", "EXAMPLE lesson")]
    return expected, ["zz-unmarked.md does not link"]


# ------------------------------------------------------------- the harness

def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def append(root, rel, text):
    with open(root / rel, "a", encoding="utf-8") as f:
        f.write(text)


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise NoVerdict(f"git {' '.join(args)} failed in the control copy: {r.stderr.strip()}")


def make_copy(src, dst):
    """Every tracked file of src, working-tree content, in a fresh repository at dst."""
    for rel in tracked(src):
        s, d = src / rel, dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if os.path.islink(s):
            os.symlink(os.readlink(s), d)
        elif s.is_file():
            shutil.copy2(s, d)
    git(dst, "init", "-q")
    git(dst, "add", "-A", "-f")


GATES = {
    "skill-references": (check_skill_references, control_skill_references),
    "bash-safe": (check_bash_safe, control_bash_safe),
    "layout": (check_layout, control_layout),
    "ascii": (check_ascii, control_ascii),
    "frontmatter": (check_frontmatter, control_frontmatter),
    "actions-pinned": (check_actions_pinned, control_actions_pinned),
    "workflow-safety": (check_workflow_safety, control_workflow_safety),
    "setup-checklist": (check_setup_checklist, control_setup_checklist),
    "portable-shell": (check_portable_shell, control_portable_shell),
    "starter-knowledge": (check_starter_knowledge, control_starter_knowledge),
}


def run(name):
    check, control = GATES[name]
    with tempfile.TemporaryDirectory(prefix=f"fleet-gate-{name}-") as tmp:
        copy = Path(tmp) / "repo"
        copy.mkdir()
        make_copy(ROOT, copy)
        expected, decoys = control(copy)
        git(copy, "add", "-A", "-f")
        got = check(copy)
    missing = [(p, why) for p, why in expected
               if not any(f.startswith(p + ":") and why in f for f in got)]
    false_red = [f for f in got if any(d in f for d in decoys)]
    if missing or false_red:
        print(f"NO VERDICT ({name}): the positive control did not discriminate, so a PASS here would mean nothing.")
        for p, why in missing:
            print(f"  planted fault not reported: {p} ({why})")
        for f in false_red:
            print(f"  decoy reported: {f}")
        return 3
    print(f"{name}: positive control fired ({len(expected)} planted fault(s) reported by path and reason, "
          f"decoys passed)")
    findings = check(ROOT)
    for f in findings:
        print(f"  {f}")
    if findings:
        print(f"FAIL ({name}): {len(findings)} finding(s)")
        return 1
    print(f"PASS ({name})")
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in GATES:
        print(f"usage: gates.py <{'|'.join(GATES)}>", file=sys.stderr)
        return 2
    try:
        return run(argv[1])
    except NoVerdict as e:
        print(f"NO VERDICT ({argv[1]}): {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
