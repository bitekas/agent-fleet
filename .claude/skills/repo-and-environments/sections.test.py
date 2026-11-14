#!/usr/bin/env python3
"""Regression guard for repo-and-environments: the section-number contract,
the internal citations, and the shape of the branch map.

The skill is prose plus a config example, so what can break silently is
structure, not code. WHAT THIS PINS, and what removing each check would let
through:

  - CONTRACT: SKILL.md carries every section number in CONTRACT below, exactly
    once, as a `## N.` or `### N.M` heading. Other documents cite this skill by
    number (SKILL.md, "How this file names things"), and an install's
    CONTEXT.md keeps the same numbers, so a deleted, renumbered or duplicated
    section strands every citer with nothing going red. CONTRACT is written by
    hand on purpose: it is the list the citers rely on, so it cannot be derived
    from the file it polices.
  - CITATIONS: every "section N" in SKILL.md and in config.example.json's
    comments resolves. A bare or `SKILL.md` citation names a SKILL.md heading;
    a `CONTEXT.md` citation names a SKILL.md heading or a section the fixture
    install's CONTEXT.md has (section 0, the role table, lives only there). A
    citation of another skill (`/release` section 12) is that skill's to keep
    and is not read here.
  - CONTEXT: the fixture install's CONTEXT.md, reached through fleetlib's
    skill_context with FLEET_CONTEXT_ROOT, numbers its sections only with
    numbers SKILL.md has or cites as `CONTEXT.md` sections, so the fixture
    teaches the matching rule rather than breaking it.
  - CONFIG: config.example.json and the fixture install's config.json carry the
    same key set, and every `branches` value is one of the environment NAMES in
    `environments` (selector_var excluded): section 2's map selects an
    environment by name, and a branch mapped to a name no role carries is a
    deploy job that cannot resolve its environment.

Negative controls: each check is re-run against a mutated copy (a deleted
heading, a duplicated heading, a citation of a missing section, a CONTEXT
section SKILL.md lacks, a branch mapped to no environment, a key missing from
the fixture config). Every mutation must produce its finding; a mutation that
does not is NO VERDICT, exit 3, because a check that cannot see a planted fault
says nothing about the real files.

Nothing is written outside a temporary directory, and HOME and XDG_* point
into it, so the real home is never read.

Run: python3 .claude/skills/repo-and-environments/sections.test.py
Exit codes: 0 pass; 1 a finding in the real files; 3 no verdict.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
FLEET_ROOT = HERE.parents[2]
SKILL = "repo-and-environments"

CONTRACT = ["1", "2", "2.1", "3", "3.1", "3.2", "3.3", "3.4", "3.5",
            "4", "4.1", "4.2", "4.3", "4.4", "4.5", "5", "5.1", "5.2",
            "6", "6.1", "6.2", "6.3", "6.4", "6.4b", "6.5", "6.6", "7", "8"]

HEADING = re.compile(r"^#{2,3} (\d+(?:\.\d+[a-z]?)?)\.?(?= )", re.M)
NUM = r"\d+(?:\.\d+[a-z]?)?"
CITE = re.compile(r"\bsections?\s+(" + NUM + r"(?:\s*(?:-|,|and)\s*" + NUM + r")*)")
OTHER_SKILL = re.compile(r"`/[a-z][a-z0-9-]*`,?\s*$")
CONTEXT_PREFIX = re.compile(r"CONTEXT\.md`?\s*$")


def headings(text):
    return HEADING.findall(text)


def citations(text):
    """(number, kind) for every section citation; kind is 'skill' or 'context'."""
    out = []
    for m in CITE.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        if OTHER_SKILL.search(before):
            continue
        kind = "context" if CONTEXT_PREFIX.search(before) else "skill"
        for n in re.findall(NUM, m.group(1)):
            out.append((n, kind))
    return out


def key_paths(obj, pre=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                yield from key_paths(v, pre + (k,))
            else:
                yield pre + (k,)


def findings(skill_md, example, context_md, fixture_cfg):
    out = []
    heads = headings(skill_md)
    for n in CONTRACT:
        c = heads.count(n)
        if c != 1:
            out.append(f"SKILL.md: section {n} appears as a heading {c} times, not once")
    context_heads = headings(context_md)
    cited_context = set()
    for text, where in ((skill_md, "SKILL.md"),
                        (" ".join(json.dumps(example).split("\\n")), "config.example.json")):
        for n, kind in citations(text):
            if kind == "context":
                cited_context.add(n)
                if n not in heads and n not in context_heads:
                    out.append(f"{where}: cites CONTEXT.md section {n}, which neither file has")
            elif n not in heads:
                out.append(f"{where}: cites section {n}, which SKILL.md has no heading for")
    for n in context_heads:
        if n not in heads and n not in cited_context:
            out.append(f"fixture CONTEXT.md: section {n} is neither a SKILL.md section nor one SKILL.md cites")
    ek, fk = set(key_paths(example)), set(key_paths(fixture_cfg))
    for k in sorted(ek - fk):
        out.append(f"fixture config.json: misses key {'.'.join(k)}")
    for k in sorted(fk - ek):
        out.append(f"fixture config.json: carries key {'.'.join(k)}, which config.example.json does not")
    for where, cfg in (("config.example.json", example), ("fixture config.json", fixture_cfg)):
        names = {v for k, v in cfg.get("environments", {}).items()
                 if not k.startswith("_") and k != "selector_var"}
        for branch, env in cfg.get("branches", {}).items():
            if not branch.startswith("_") and env not in names:
                out.append(f"{where}: branch {branch!r} maps to {env!r}, which is no environment name")
    return out


def load():
    sys.path.insert(0, str(FLEET_ROOT / "lib"))
    from fleetlib import paths  # noqa: E402
    ctx = paths.skill_context(SKILL)
    return ((HERE / "SKILL.md").read_text(encoding="utf-8"),
            json.loads((HERE / "config.example.json").read_text(encoding="utf-8")),
            (ctx / "CONTEXT.md").read_text(encoding="utf-8"),
            json.loads((ctx / "config.json").read_text(encoding="utf-8")))


def mutations(skill_md, example, context_md, fixture_cfg):
    """(name, mutated inputs, substring the finding must contain)."""
    bad_branch = json.loads(json.dumps(example))
    bad_branch["branches"]["zz-control"] = "no-such-env"
    missing_key = json.loads(json.dumps(fixture_cfg))
    del missing_key["repo"]["slug"]
    return [
        ("deleted heading", (skill_md.replace("\n### 4.5 ", "\n### four-five ", 1), example, context_md, fixture_cfg),
         "section 4.5 appears as a heading 0 times"),
        ("duplicated heading", (skill_md + "\n### 3.3 A second 3.3\n", example, context_md, fixture_cfg),
         "section 3.3 appears as a heading 2 times"),
        ("dangling citation", (skill_md + "\nSee section 9.9 for nothing.\n", example, context_md, fixture_cfg),
         "cites section 9.9"),
        ("dangling CONTEXT citation", (skill_md + "\n`CONTEXT.md` section 9.8 has nothing.\n", example, context_md, fixture_cfg),
         "cites CONTEXT.md section 9.8"),
        ("CONTEXT section SKILL.md lacks", (skill_md, example, context_md + "\n## 9. Extra\n", fixture_cfg),
         "section 9 is neither"),
        ("branch to no environment", (skill_md, bad_branch, context_md, fixture_cfg),
         "'zz-control' maps to 'no-such-env'"),
        ("fixture key missing", (skill_md, example, context_md, missing_key),
         "misses key repo.slug"),
    ]


def main():
    tmp = tempfile.mkdtemp(prefix="fleet-rae-sections-")
    try:
        for var in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            os.environ[var] = os.path.join(tmp, var.lower())
        if not os.environ.get("FLEET_CONTEXT_ROOT"):
            os.environ["FLEET_CONTEXT_ROOT"] = str(FLEET_ROOT / "tests" / "fixtures" / "install")
        try:
            inputs = load()
        except Exception as e:  # the instrument could not be established
            print(f"NO VERDICT: cannot read the skill or the fixture install context: {e}")
            return 3
        # The citation reader must see real citations before its silence means anything.
        if len(citations(inputs[0])) < 50 or not any(k == "context" for _, k in citations(inputs[0])):
            print("NO VERDICT: the citation reader found too few citations in SKILL.md to be trusted")
            return 3
        dead = []
        for name, args, want in mutations(*inputs):
            got = findings(*args)
            if any(want in f for f in got):
                print(f"[control] {name}: caught")
            else:
                dead.append(name)
                print(f"[control] {name}: NOT caught (findings: {got})")
        if dead:
            print(f"NO VERDICT: {len(dead)} negative control(s) did not fire: {', '.join(dead)}")
            return 3
        real = findings(*inputs)
        for f in real:
            print(f"[FAIL] {f}")
        if real:
            print(f"FAIL: {len(real)} finding(s)")
            return 1
        print(f"PASS: {len(CONTRACT)} contract sections, {len(citations(inputs[0]))} citations, "
              f"{len(headings(inputs[2]))} fixture CONTEXT sections, branch map consistent")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
