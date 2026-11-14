#!/usr/bin/env python3
"""Regression guard for e2e-suite's config contract.

SKILL.md names no value: it cites config keys in backticks (`e2e.runner`), and
an agent reads each value out of the install's config.json. Nothing reads that
file at run time, so nothing else notices when the three drift apart. This test
holds them to one key set:

  1. config.example.json parses, and every key SKILL.md cites in backticks under
     `e2e.`, `app.` or `checks.` resolves to a key in it (a leaf, or a block
     holding leaves). A citation with no key behind it is a value a stranger who
     fills in the example never writes, and an agent then has nothing to read.
  2. The install's config.json - `fleetlib.paths.skill_context('e2e-suite')`,
     which under tests/run-all.sh is the fixture install - carries every key of
     the example, except that a block the example marks `"_optional": true` may
     be left out WHOLE. A present optional block is held complete. The install
     carries no key the example lacks: a key only the install has is one
     SKILL.md cannot mean, and is most often a typo of one it does.
  3. Controls, run before the real files are judged: the citation scan must find
     citations known to be present (positive control: a scan that finds nothing
     agrees with every example), and each comparison must go red on a planted
     fault - a citation of a missing key, an install short a required key, an
     install with an unknown key, an install without a required block, a partial
     optional block - and stay green on an optional block left out whole. A
     control that does not behave issues NO VERDICT, never a pass.

To check an install other than the fixture, point fleetlib at it:
  FLEET_CONTEXT_ROOT=<install root> python3 .claude/skills/e2e-suite/config.test.py

Exit 0 every check passed; 1 a check failed; 3 NO VERDICT (a control did not
behave, or the install's config.json could not be resolved or read).
Stdlib and fleetlib only. Reads files, writes none.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
FLEET_ROOT = HERE.parents[2]
sys.path.insert(0, str(FLEET_ROOT / "lib"))

from fleetlib import FleetError, paths  # noqa: E402

SKILL = "e2e-suite"
CITATION = re.compile(r"`((?:e2e|app|checks)(?:\.[a-z_]+)+)`")
KNOWN_CITED = ("e2e.runner", "e2e.lock.library", "app.navigation_calls", "checks.commands")


class NoVerdict(Exception):
    pass


def keyset(obj, pre=()):
    """(leaves, optional): every key path to a non-object value, `_` keys
    dropped, and the paths of blocks marked "_optional": true."""
    leaves, optional = set(), set()
    if isinstance(obj, dict):
        if obj.get("_optional") is True:
            optional.add(pre)
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            sub_leaves, sub_optional = keyset(v, pre + (k,))
            leaves |= sub_leaves
            optional |= sub_optional
        if not leaves and pre:
            leaves.add(pre)
    else:
        leaves.add(pre)
    return leaves, optional


def citations(text):
    return sorted(set(CITATION.findall(text)))


def unresolved(cited, leaves):
    """Cited key paths that are neither a leaf nor a block holding one."""
    out = []
    for c in cited:
        path = tuple(c.split("."))
        if not any(leaf[:len(path)] == path for leaf in leaves):
            out.append(c)
    return out


def compare(example, install):
    """Findings for an install config against the example's key set."""
    want, optional = keyset(example)
    have, _ = keyset(install)
    findings = []
    for leaf in sorted(want - have):
        block = next((o for o in optional if leaf[:len(o)] == o), None)
        if block is not None and not any(h[:len(block)] == block for h in have):
            continue  # an optional block left out whole
        findings.append(f"install config misses `{'.'.join(leaf)}`")
    for leaf in sorted(have - want):
        findings.append(f"install config carries `{'.'.join(leaf)}`, which config.example.json does not")
    return findings


def check(name, ok, detail=""):
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok or not detail else " - " + detail))
    return ok


def controls():
    """Each comparison must go red on its planted fault; else NO VERDICT."""
    found = citations("A `e2e.runner` and `e2e.lock.library`, a path `e2e/`, a word e2e.x.")
    if found != ["e2e.lock.library", "e2e.runner"]:
        raise NoVerdict(f"the citation scan read {found} from a fixed sentence")
    example = {"a": {"b": 1, "c": [1, 2]}, "opt": {"_optional": True, "x": 1, "y": 2},
               "req": {"z": None}}
    leaves, _ = keyset(example)
    planted = {
        "citation of a missing key": (unresolved(["a.b", "a", "opt.x", "a.nope"], leaves), ["a.nope"]),
        "install short a required key": (compare(example, {"a": {"b": 1}, "req": {"z": 0}}),
                                         ["install config misses `a.c`"]),
        "install with an unknown key": (compare(example, {"a": {"b": 1, "c": [], "d": 2}, "req": {"z": 0}}),
                                        ["install config carries `a.d`, which config.example.json does not"]),
        "install without a required block": (compare(example, {"a": {"b": 1, "c": []}}),
                                              ["install config misses `req.z`"]),
        "partial optional block": (compare(example, {"a": {"b": 1, "c": []}, "opt": {"x": 1}, "req": {"z": 0}}),
                                   ["install config misses `opt.y`"]),
        "optional block left out whole": (compare(example, {"a": {"b": 1, "c": []}, "req": {"z": 0}}), []),
    }
    for name, (got, want) in planted.items():
        if got != want:
            raise NoVerdict(f"control '{name}': expected {want}, got {got}")
        print(f"[CONTROL] {name}: {'red as planted' if want else 'green as planted'}")


def load(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NoVerdict(f"cannot read {what} {path}: {exc}") from None


def main():
    try:
        controls()
        example = load(HERE / "config.example.json", "the example")
        skill_text = (HERE / "SKILL.md").read_text(encoding="utf-8")
        try:
            install_path = paths.skill_context(SKILL) / "config.json"
        except FleetError as exc:
            raise NoVerdict(f"no install context resolves: {exc}") from None
        install = load(install_path, "the install config")
    except NoVerdict as exc:
        print(f"NO VERDICT: {exc}")
        return 3

    leaves, _ = keyset(example)
    cited = citations(skill_text)
    ok = True
    missing_known = [k for k in KNOWN_CITED if k not in cited]
    if missing_known:
        print(f"NO VERDICT: SKILL.md no longer cites {missing_known}, so the scan's positive control is gone")
        return 3
    print(f"[INFO] SKILL.md cites {len(cited)} config key(s); install config: {install_path}")
    bad = unresolved(cited, leaves)
    ok &= check("every key SKILL.md cites is in config.example.json", not bad,
                "; ".join(f"`{c}` is cited and has no key" for c in bad))
    findings = compare(example, install)
    ok &= check("the install config carries the example's key set", not findings, "; ".join(findings))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
