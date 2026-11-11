#!/usr/bin/env python3
"""Check the mechanical half of the index rule.

Verifies, for a knowledge tree:
  - every directory has an index.md
  - every .md file is linked from its own directory's index
  - every subdirectory is linked from its parent's index
  - every relative link in an index resolves to something that exists

It cannot tell whether a description is ACCURATE, only whether the wiring is
intact. An index that lists the right files with wrong descriptions passes here
and is still the failure this rule exists to prevent, so read what you write.

There is no exempt filename. An earlier form of this checker skipped a rulebook
file at the tree root, which is a hole a reader cannot see from the index they
are trusting; the conventions live in the skill instead, so the store root holds
an index and knowledge and nothing else.

A link target is the real relative path and nothing looser. The draft this
came from also accepted an extension-less `[Two](two)` as linking `two.md`,
while the link-resolution check below still resolved that target on disk and
reported it missing: the same index was simultaneously linked and dangling, and
which message a reader saw depended on which check they read first. One rule
instead, so the two checks cannot disagree.

The root is an ARGUMENT, never read from config: that is what keeps this
runnable against a throwaway fixture tree with no install present, which is what
its own test does.

Usage:  check_indexes.py <root> [--quiet]
Exit:   0 clean, 1 problems found, 2 unusable arguments.
"""
import os
import re
import sys

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
INDEX = "index.md"


def links_in(path):
    """Relative link targets in a markdown file, ignoring URLs and anchors."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return set()
    out = set()
    for target in LINK.findall(text):
        if "://" in target or target.startswith("#") or target.startswith("mailto:"):
            continue
        out.add(target.split("#", 1)[0].rstrip("/"))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    quiet = "--quiet" in sys.argv
    if not args:
        print(__doc__.strip())
        return 2
    root = os.path.abspath(args[0])
    if not os.path.isdir(root):
        print(f"not a directory: {root}")
        return 2

    problems = []
    checked = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        index_path = os.path.join(dirpath, INDEX)

        if not os.path.isfile(index_path):
            problems.append(f"{rel_dir}/ has no {INDEX}")
            continue
        checked += 1

        targets = links_in(index_path)

        # every sibling .md (except the index itself) must be linked
        for name in sorted(filenames):
            if not name.endswith(".md") or name == INDEX:
                continue
            if name not in targets:
                problems.append(f"{rel_dir}/{INDEX} does not link {name}")

        # every subdirectory must be linked, usually as name/index.md
        for name in sorted(dirnames):
            if not any(t == name or t.startswith(name + "/") for t in targets):
                problems.append(f"{rel_dir}/{INDEX} does not link subfolder {name}/")

        # every link must resolve
        for target in sorted(targets):
            if not os.path.exists(os.path.join(dirpath, target)):
                problems.append(f"{rel_dir}/{INDEX} links missing {target}")

    if problems:
        for p in problems:
            print("  " + p.replace("./", "", 1))
        print(f"\n{len(problems)} problem(s) across {checked} index file(s)")
        return 1
    if not quiet:
        print(f"indexes clean: {checked} checked under {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
