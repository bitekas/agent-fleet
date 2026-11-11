#!/usr/bin/env python3
"""Regression guard for check_indexes.py.

Offline, deterministic, fixture-driven: every case below builds a throwaway
knowledge tree under a temp directory and runs the real script against it as a
subprocess, so the EXIT CODE contract is exercised and not just the internals.
No network, no config, no store.

The point of the file is the negative controls. A checker that has never been
seen to fail is not evidence: it manufactures confidence, and this one would
report a silently broken store as clean. So every rule the script claims to
enforce has a fixture here that breaks exactly that rule and no other, and each
case asserts the PROBLEM TEXT as well as the exit code - a fixture that goes red
for the wrong reason would otherwise pass as a working control.

It also pins the one deliberate behaviour change from the draft this script came
from: there is NO exempt filename at the tree root. The draft skipped a
`knowledge.md` rulebook there. In this tree the conventions are SKILL.md, so
such a file would be a second copy of them, and if one exists anyway it is a
knowledge file like any other and must be linked.

Run: python3 .claude/skills/knowledge-base/check_indexes.test.py
Exits nonzero on any failure.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_indexes.py")

_failures = []
_tmp = tempfile.mkdtemp(prefix="check-indexes-test-")


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


def tree(name, files):
    """Build a fixture tree: {relative path: file contents}. Returns its root."""
    root = os.path.join(_tmp, name)
    for rel, body in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    os.makedirs(root, exist_ok=True)
    return root


def run(*args):
    """(exit code, combined output) from the real script."""
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


# The reference tree every negative control is a single mutation of. It exercises
# each accepted link form on purpose: a subfolder linked as `name/index.md`, a
# second one linked as bare `name/`, a file linked by its real path, plus a URL,
# an anchor and a mailto that must all be ignored rather than chased as dangling
# relative links.
CLEAN = {
    "index.md": (
        "# Root\n\nWhat belongs here.\n\n"
        "## Subfolders\n"
        "- [alpha/](alpha/index.md) - the alpha topic\n"
        "- [beta/](beta/) - the beta topic\n\n"
        "## Files\n"
        "- [Loose note](loose.md) - a note that lives at the root\n"
        "- [Elsewhere](https://example.com/docs) - not a relative link\n"
        "- [Section](#subfolders) - an anchor, not a file\n"
        "- [Someone](mailto:jane.doe@example.com) - not a file either\n"
    ),
    "loose.md": "# Loose\n",
    "alpha/index.md": (
        "# Alpha\n\n## Subfolders\n- [deep/](deep/index.md) - deeper\n\n"
        "## Files\n- [One](one.md) - the first thing\n"
    ),
    "alpha/one.md": "# One\n",
    "alpha/deep/index.md": "# Deep\n\n## Files\n- [Two](two.md) - the second thing\n",
    "alpha/deep/two.md": "# Two\n",
    "beta/index.md": "# Beta\n\n## Files\n- [Three](three.md) - the third thing\n",
    "beta/three.md": "# Three\n",
}


def mutate(changes=None, **extra):
    """A copy of CLEAN with paths replaced, or removed when the value is None."""
    out = dict(CLEAN)
    for rel, body in {**(changes or {}), **extra}.items():
        if body is None:
            out.pop(rel, None)
        else:
            out[rel] = body
    return out


# === 0. POSITIVE CONTROL: the clean tree must pass, or every red below is noise.
rc, out = run(tree("clean", CLEAN))
check("a clean tree exits 0", rc == 0, f"rc={rc} out={out!r}")
check("a clean tree reports how many indexes it checked", "4" in out and "clean" in out,
      f"out={out!r}")
check("--quiet prints nothing on a clean tree",
      run(tree("clean", CLEAN), "--quiet") == (0, ""), f"got={run(tree('clean', CLEAN), '--quiet')!r}")

# === 1. NEGATIVE CONTROL: a directory with no index.md.
rc, out = run(tree("no-index", mutate({"alpha/deep/index.md": None})))
check("missing index.md is caught", rc == 1 and "has no index.md" in out, f"rc={rc} out={out!r}")
check("missing index.md names the directory", "alpha/deep/" in out, f"out={out!r}")

# === 2. NEGATIVE CONTROL: a .md file its own directory's index does not link.
unlinked = mutate()
unlinked["alpha/orphan.md"] = "# Orphan\n"
rc, out = run(tree("unlinked-file", unlinked))
check("an unlinked file is caught",
      rc == 1 and "does not link orphan.md" in out, f"rc={rc} out={out!r}")

# === 3. NEGATIVE CONTROL: a subfolder the parent index does not link. The folder
#        carries its own valid index, so the ONLY breakage is the parent's wiring.
unlinked_dir = mutate()
unlinked_dir["beta/hidden-topic/index.md"] = "# Hidden topic\n\nNothing yet.\n"
rc, out = run(tree("unlinked-subfolder", unlinked_dir))
check("an unlinked subfolder is caught",
      rc == 1 and "does not link subfolder hidden-topic/" in out, f"rc={rc} out={out!r}")

# === 4. NEGATIVE CONTROL: an index link pointing at something that is not there.
rc, out = run(tree("dangling", mutate({
    "beta/index.md": "# Beta\n\n## Files\n- [Three](three.md) - ok\n- [Gone](gone.md) - deleted\n"})))
check("a dangling link is caught",
      rc == 1 and "links missing gone.md" in out, f"rc={rc} out={out!r}")
check("a dangling link does not also mis-report the file that IS there",
      "three.md" not in out.replace("links missing gone.md", ""), f"out={out!r}")

# === 5. THE RESOLUTION: knowledge.md at the root is NOT exempt.
#        The draft this came from skipped it, so a rulebook could sit at the root
#        unlinked. Here the conventions are SKILL.md and there is no rulebook, so
#        a file with that name is knowledge like any other. This case is what
#        stops the old special case being reintroduced by someone porting the
#        draft again.
rulebook = mutate()
rulebook["knowledge.md"] = "# Some knowledge that happens to have this name\n"
rc, out = run(tree("root-knowledge-md", rulebook))
check("knowledge.md at the root is NOT exempt from the index rule",
      rc == 1 and "does not link knowledge.md" in out, f"rc={rc} out={out!r}")
# ...and linking it is all it takes to go green, i.e. the rule is satisfiable.
rulebook_linked = dict(rulebook)
rulebook_linked["index.md"] = CLEAN["index.md"].replace(
    "- [Loose note](loose.md) - a note that lives at the root\n",
    "- [Loose note](loose.md) - a note that lives at the root\n"
    "- [Named knowledge](knowledge.md) - linked like anything else\n")
rc, out = run(tree("root-knowledge-md-linked", rulebook_linked))
check("linking it is enough to make the tree clean again", rc == 0, f"rc={rc} out={out!r}")

# === 5b. NEGATIVE CONTROL: an extension-less link. The draft this script came
#         from accepted `[Two](two)` as linking `two.md` in one check while the
#         link-resolution check reported that same target missing, so one index
#         was simultaneously linked and dangling and which message a reader saw
#         depended on which check they read first. One rule now: the tree is
#         dirty, and both messages agree about which file is the problem.
rc, out = run(tree("extensionless", mutate({
    "beta/index.md": "# Beta\n\n## Files\n- [Three](three) - no extension\n"})))
check("an extension-less link does not satisfy the index rule",
      rc == 1 and "does not link three.md" in out, f"rc={rc} out={out!r}")
check("...and the same link is reported dangling, from the one rule",
      "links missing three" in out, f"out={out!r}")

# === 6. NEGATIVE CONTROL, compound: several problems are all reported, not just
#        the first. A checker that stopped at the first finding would send a
#        writer round the loop once per defect.
compound = mutate({"alpha/deep/index.md": None})
compound["beta/orphan.md"] = "# Orphan\n"
rc, out = run(tree("compound", compound))
check("every problem is reported, not only the first",
      rc == 1 and "has no index.md" in out and "does not link orphan.md" in out
      and "links missing deep/index.md" in out and "3 problem(s)" in out,
      f"rc={rc} out={out!r}")

# === 7. Hidden directories are skipped. A store under version control or holding
#        an editor's scratch dir must not read as a wall of missing indexes.
hidden = mutate()
hidden[".git/config"] = "[core]\n"
hidden[".obsidian/workspace.json"] = "{}\n"
rc, out = run(tree("hidden", hidden))
check("dot-directories are skipped, not reported as missing indexes",
      rc == 0, f"rc={rc} out={out!r}")

# === 8. Usage contract: exit 2 is neither clean nor dirty, it is unusable input,
#        so a caller cannot mistake a typo'd path for a healthy store.
rc, out = run()
check("no argument exits 2 and prints usage", rc == 2 and "Usage:" in out, f"rc={rc} out={out!r}")
rc, out = run(os.path.join(_tmp, "does-not-exist"))
check("a nonexistent root exits 2, NOT 0", rc == 2 and "not a directory" in out,
      f"rc={rc} out={out!r}")
rc, out = run(os.path.join(_tmp, "clean", "loose.md"))
check("a file given as the root exits 2", rc == 2 and "not a directory" in out,
      f"rc={rc} out={out!r}")

# === 9. The minimal real store: a root and its index, which is exactly what the
#        install procedure creates. It must be clean the moment it is made, or
#        the very first check after initialization is a false alarm.
rc, out = run(tree("minimal", {"index.md": "# Knowledge base\n\nThe root.\n"}))
check("a freshly initialized store (root + index.md, no topics) is clean",
      rc == 0, f"rc={rc} out={out!r}")

shutil.rmtree(_tmp, ignore_errors=True)

print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
