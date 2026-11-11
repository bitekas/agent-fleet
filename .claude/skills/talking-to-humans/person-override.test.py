#!/usr/bin/env python3
"""person-override.test.py - rules 1, 4 and 5 of SKILL.md carry the one
exception to one-question-at-a-time, and the convention key it names is real.

The subject is PROSE an agent follows, so the test reads the STATEMENT of the
rule, not an effect: no code enforces one question at a time, and an agent that
never saw the exception behaves exactly like one told there is none. Rule 1
without it reads "even when the person asks for the full list" with nothing
after it, which is how an agent refuses a person's own recorded wish.

What each check pins, and what removing it lets through:

  1. Rule 1 (its own text, never the whole file) names the command
     `fleet settings conventions.<key>`, "standing request", "for that person
     only" and `null`. Without them the exception, its scope (one person, never
     the whole install) or its fallback (no convention or no note: the rule as
     written) can be edited away with nothing red.
  2. Rules 4 and 5 each cite "rule 1's exception". Rule 4 says "never the
     list" and rule 5 refuses the full list outright; uncited, each contradicts
     the exception for exactly the person it exists for.
  3. The key rule 1 names is in fleetlib.manifest.CONVENTION_KEYS, and
     CONVENTIONS.md's row for it names this skill as its reader. A key renamed
     in the schema and not here leaves the rule pointing at a setting that does
     not exist; check 4 would see that too, but only this check names it.
  4. The command rule 1 tells an agent to run, run for real through bin/fleet
     against a throwaway install: with the key ABSENT it prints `null` (an
     install manifest that never set the key still loads, and reads as "no
     convention"); with it present it prints the value written. A schema
     without the key refuses the same command ("no setting ..."), so `null`
     there is evidence the schema carries the key, not a default echoed back.

THE CONTROL, and why a pass without it means nothing. Before checks 1 to 3 may
report no finding, the same checker runs over mutated copies: each required
phrase cut from rule 1 (and appended at the end of the file, so a phrase found
ANYWHERE but rule 1 is not mistaken for rule 1's), the citation cut from rule 4
and from rule 5, the key renamed to one the schema lacks, and CONVENTIONS.md's
row for the key naming another reader. Every mutant must come back with a
finding. One that comes back clean means the checker cannot see the defect it
exists for: that is NO VERDICT, never a pass. The parser must also find the
rules numbered 1 to N in order (N >= 5) with rule 1 opening on "One question at
a time"; a SKILL.md it cannot parse is NO VERDICT too (the subject was not
reached), never "no findings". A finding on the real SKILL.md is a FAIL without
the control: the mutants are cut from the very phrases a finding says are
missing, and a false red is the visible kind.

Outcomes: exit 0 PASS; 1 FAIL, every finding printed; 3 NO VERDICT (the parser
did not reach the rules, or a control mutant came back clean). Nothing outside a
temporary directory is written; bin/fleet runs with HOME, the XDG directories
and FLEET_CONTEXT_ROOT pointed into it and every other fleet variable unset.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
SKILL_DIR = Path(os.path.realpath(__file__)).parent
REPO = SKILL_DIR.parents[2]
sys.path.insert(0, str(REPO / "lib"))
from fleetlib import manifest  # noqa: E402

SKILL_MD = SKILL_DIR / "SKILL.md"
CONVENTIONS_MD = REPO / "CONVENTIONS.md"
FLEET = REPO / "bin" / "fleet"
SKILL_NAME = SKILL_DIR.name

RULE1_PHRASES = ("standing request", "for that person only", "`null`")
CITATION = "rule 1's exception"
COMMAND = re.compile(r"`fleet settings conventions\.([a-z_]+)`")
RULE = re.compile(r"^(\d+)\. (.*)$")


class NoVerdict(Exception):
    pass


def rules(text):
    """{number: text} of the numbered rules; a continuation line joins its rule."""
    out, cur = {}, None
    for line in text.splitlines():
        m = RULE.match(line)
        if m:
            cur = int(m.group(1))
            out[cur] = m.group(2)
        elif cur is not None and line.startswith("   ") and line.strip():
            out[cur] += " " + line.strip()
        elif not line.strip():
            cur = None
    return out


def parsed(text):
    """The rules, or NO VERDICT unless they are numbered 1 to N in order (N >= 5,
    the last rule read here) with rule 1 on one question at a time."""
    r = rules(text)
    if (sorted(r) != list(range(1, len(r) + 1)) or len(r) < 5
            or not r[1].startswith("**One question at a time")):
        raise NoVerdict(f"SKILL.md: expected rules numbered 1 to N (N >= 5) with rule 1 on one "
                        f"question at a time, parsed {sorted(r)}")
    return r


def findings(text, keys, conventions_md):
    r = parsed(text)
    out = []
    keys_named = COMMAND.findall(r[1])
    if not keys_named:
        out.append("rule 1 does not name `fleet settings conventions.<key>`")
    for k in keys_named:
        if k not in keys:
            out.append(f"rule 1 names conventions.{k}, which is not a schema-1 convention key")
        row = re.search(rf"^\| `{re.escape(k)}` \|.*$", conventions_md, re.M)
        if k in keys and not (row and f"`{SKILL_NAME}`" in row.group(0)):
            out.append(f"CONVENTIONS.md: the `{k}` row does not name the `{SKILL_NAME}` skill as its reader")
    for p in RULE1_PHRASES:
        if p not in r[1]:
            out.append(f"rule 1 lacks {p!r}")
    for n in (4, 5):
        if CITATION not in r[n].lower():
            out.append(f"rule {n} does not cite {CITATION!r}")
    return out


def mutants(text, conventions_md):
    """(what, SKILL.md, CONVENTIONS.md), one of the two mutated, for every defect
    checks 1 to 3 must see. Built only from a text with no finding, so every
    phrase it cuts is there to cut; one that is not is NO VERDICT."""
    r = parsed(text)
    lines = text.splitlines(keepends=True)
    at = {n: next(i for i, ln in enumerate(lines) if ln.startswith(f"{n}. ")) for n in (1, 4, 5)}

    def edit(n, old, new, tail=""):
        if old not in lines[at[n]]:
            raise NoVerdict(f"control: {old!r} is not on rule {n}'s first line, so its mutant cannot be built")
        cp = list(lines)
        cp[at[n]] = cp[at[n]].replace(old, new)
        return "".join(cp) + tail, conventions_md

    out = [(f"rule 1 without {p!r}", *edit(1, p, "", f"\n{p}\n")) for p in RULE1_PHRASES]
    cmd = COMMAND.search(r[1])
    out.append(("rule 1 without the command", *edit(1, cmd.group(0), "", f"\n{cmd.group(0)}\n")))
    out.append(("rule 1 naming a key the schema lacks",
                *edit(1, cmd.group(0), "`fleet settings conventions.no_such_key`")))
    for n in (4, 5):
        hit = re.search(re.escape(CITATION), lines[at[n]], re.I)
        if not hit:
            raise NoVerdict(f"control: {CITATION!r} is not on rule {n}'s first line")
        out.append((f"rule {n} without the citation", *edit(n, hit.group(0), "")))
    row = re.search(rf"^\| `{re.escape(cmd.group(1))}` \|.*$", conventions_md, re.M)
    out.append((f"CONVENTIONS.md's `{cmd.group(1)}` row naming another reader", text,
                conventions_md.replace(row.group(0), row.group(0).replace(f"`{SKILL_NAME}`", "`agent`"))))
    return out


def fleet_settings(tmp, key, conventions, files=()):
    """`fleet settings conventions.<key>` in a fresh install; (exit, stdout, stderr)."""
    root = Path(tmp) / "inst"
    shutil.rmtree(root, ignore_errors=True)
    m = {"schema": 1, "fleet": {"repo": "https://example.com/example/agent-fleet.git", "min_tag": "v1.0.0"},
         "skills": ["chat-transport", "slack-communication", SKILL_NAME],
         "transports": {"enabled": ["slack"], "default": "slack"}, "conventions": conventions}
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "fleet.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n", encoding="utf-8")
    home = Path(tmp) / "home"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "XDG_CONFIG_HOME": str(home / "cfg"), "XDG_STATE_HOME": str(home / "state"),
           "XDG_DATA_HOME": str(home / "data"), "FLEET_CONTEXT_ROOT": str(root)}
    r = subprocess.run([sys.executable, "-B", str(FLEET), "settings", f"conventions.{key}"], env=env,
                       cwd=tmp, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout, r.stderr


def main():
    text = SKILL_MD.read_text(encoding="utf-8")
    conv = CONVENTIONS_MD.read_text(encoding="utf-8")
    keys = manifest.CONVENTION_KEYS
    try:
        fails = findings(text, keys, conv)
        if not fails:  # the control gates a pass; a finding stands on its own
            for what, skill_text, conv_text in mutants(text, conv):
                if not findings(skill_text, keys, conv_text):
                    raise NoVerdict(f"control: the mutant '{what}' came back with no finding")
                print(f"[control] {what}: reported")
    except NoVerdict as exc:
        print(f"NO VERDICT: {exc}")
        return 3

    # Check 4. With no key in rule 1 (already a finding), the command is still run
    # for the key this skill is written against, so the run reports on both.
    named = COMMAND.findall(rules(text)[1])
    key = named[0] if named else "people_notes"
    with tempfile.TemporaryDirectory(prefix="fleet-t2h-test-") as tmp:
        rc, out, err = fleet_settings(tmp, key, {"release": None})
        if (rc, out) != (0, "null\n"):
            fails.append(f"fleet settings conventions.{key} with the key absent: exit {rc}, "
                         f"stdout {out!r}, stderr {err.strip()!r}; want exit 0 and null")
        else:
            print(f"[ok] key absent: fleet settings conventions.{key} -> null")
        value = {"doc": "docs/people-notes.md", "section": "Questions"}
        rc, out, err = fleet_settings(tmp, key, {key: value}, files=["docs/people-notes.md"])
        got = None
        try:
            got = json.loads(out)
        except ValueError:
            pass
        if rc != 0 or got != value:
            fails.append(f"fleet settings conventions.{key} with the key set: exit {rc}, "
                         f"stdout {out!r}, stderr {err.strip()!r}; want exit 0 and {value}")
        else:
            print(f"[ok] key set: fleet settings conventions.{key} -> {json.dumps(got)}")

    for f in fails:
        print(f"[FAIL] {f}")
    if fails:
        print(f"FAIL: {len(fails)} finding(s)")
        return 1
    print("PASS: rules 1, 4 and 5 carry the exception; its key resolves through fleet settings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
