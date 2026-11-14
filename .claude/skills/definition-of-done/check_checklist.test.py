#!/usr/bin/env python3
"""Regression guard for check_checklist.py.

Offline, deterministic, fixture-driven: every case copies a fixture into a
throwaway git repository under a temp directory and runs the REAL script
against it as a subprocess, so the exit-code contract is exercised and not
just the internals. No network. The config is the fleet's fixture install
(tests/fixtures/install/.claude/skills/definition-of-done/config.json), passed
with --config, except in the cases that prove the default resolution through
fleetlib, which set FLEET_CONTEXT_ROOT to that fixture install. HOME and the
XDG directories point into the temp directory, and the git identity is pinned
per run through the environment, with the global and system git config
switched off, so the machine's own identity and install cannot leak into a
verdict.

The point of the file is the negative controls. A checker that has never been
seen to refuse is not evidence. So every refusal the script claims has a case
here that breaks exactly one thing in fixtures/pass.md, and each asserts the
FINDING TEXT and its line as well as the exit code: a fixture that goes red for
the wrong reason would otherwise pass as a working control. The exit-2 cases
assert that nothing malformed is ever judged, in either direction.

fixtures/handoff-replay.md is a hand-off whose pixel check covered only the
frames the task froze, written as a checklist; the test asserts the checker
refuses it with exactly the pixel-check findings that hand-off carried, its
missing bug hunt and its missing presentation to the requester, and nothing
else.

Run: python3 .claude/skills/definition-of-done/check_checklist.test.py
Exits nonzero on any failure. Count the checks off its own output.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

# realpath: run through a skill link, the link directory has no fleet above it.
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPT = os.path.join(HERE, "check_checklist.py")
FIXTURES = os.path.join(HERE, "fixtures")
TEMPLATE = os.path.join(HERE, "feature-checklist.template.md")
EXAMPLE_CONFIG = os.path.join(HERE, "config.example.json")
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
CONFIG = os.path.join(FIXTURE_INSTALL, ".claude", "skills", "definition-of-done", "config.json")

_failures = []
_count = [0]
_tmp = tempfile.mkdtemp(prefix="check-checklist-test-")
ABS_EVIDENCE = os.path.join(_tmp, "outside", "12-default-verdict.txt")
os.makedirs(os.path.dirname(ABS_EVIDENCE))
with open(ABS_EVIDENCE, "w") as f:
    f.write("PASS 0.21% / flow 0.4px\n")


def check(name, cond, detail=""):
    _count[0] += 1
    status = "PASS" if cond else "FAIL"
    print("[%s] %s" % (status, name) + (" - %s" % detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def env_for(runner, context_root=FIXTURE_INSTALL):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("GIT_", "XDG_")) and k not in ("FLEET_CONTEXT_ROOT", "CLAUDE_CONFIG_DIR")}
    e.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": _tmp,
              "XDG_CONFIG_HOME": os.path.join(_tmp, "xdg-config"),
              "XDG_STATE_HOME": os.path.join(_tmp, "xdg-state"),
              "XDG_CACHE_HOME": os.path.join(_tmp, "xdg-cache"),
              "XDG_DATA_HOME": os.path.join(_tmp, "xdg-data"),
              "FLEET_HOST_CONFIG": os.path.join(_tmp, "no-host.json"),
              "FLEET_CONTEXT_ROOT": context_root})
    if runner is not None:
        e.update({"GIT_AUTHOR_NAME": runner, "GIT_AUTHOR_EMAIL": "%s@example.com" % runner.lower(),
                  "GIT_COMMITTER_NAME": runner, "GIT_COMMITTER_EMAIL": "%s@example.com" % runner.lower()})
    return e


def g(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       env=env_for("Builder"))
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr))
    return p.stdout.strip()


_n = [0]


def repo(files, commit=True):
    """A throwaway git repo holding the evidence the pass fixture names plus
    `files` ({relpath: text}). COMMIT_SHA in any file becomes a real commit, an
    ancestor of HEAD; SIDE_SHA becomes a real commit on a side branch, which
    is NOT an ancestor of HEAD."""
    _n[0] += 1
    root = os.path.join(_tmp, "repo%d" % _n[0])
    os.makedirs(root)
    g(root, "init", "-q")
    g(root, "config", "user.useConfigOnly", "true")
    base = {"docs/plan.md": "# Plan\n\nT1, T2\n",
            "e2e/cart-sort.spec.ts": "// spec\n" * 20}
    for rel, body in base.items():
        write(root, rel, body)
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", "evidence")
    sha = g(root, "rev-parse", "HEAD")
    g(root, "checkout", "-q", "-b", "side")
    g(root, "commit", "-q", "--allow-empty", "-m", "side")
    side = g(root, "rev-parse", "HEAD")
    g(root, "checkout", "-q", "-")
    for rel, body in files.items():
        write(root, rel, body.replace("COMMIT_SHA", sha).replace("SIDE_SHA", side)
              .replace("ABS_EVIDENCE", ABS_EVIDENCE))
    if commit and files:
        g(root, "add", "-A")
        g(root, "commit", "-q", "-m", "checklists")
    return root


def write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


PASS = fixture("pass.md")
CL = "docs/checklists/example-feature.md"
CHAT = "https://chat.example.com/feature-thread/m/"


def run(args, runner="Rex", cwd=None, script=SCRIPT, config=CONFIG, context_root=FIXTURE_INSTALL):
    """(exit code, stdout+stderr) from the real script."""
    cmd = [sys.executable, script] + list(args)
    if config is not None:
        cmd += ["--config", config]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       env=env_for(runner, context_root), cwd=cwd or _tmp)
    return p.returncode, p.stdout + p.stderr


def run_one(body, name=CL, runner="Rex", commit=True):
    root = repo({name: body}, commit=commit)
    return run([os.path.join(root, name)], runner=runner)


def line_of(body, needle):
    for i, l in enumerate(body.split("\n"), 1):
        if needle in l:
            return i
    raise AssertionError("fixture has no line containing %r" % needle)


def mutate(old, new, body=PASS):
    assert old in body, "fixture lacks %r" % old
    return body.replace(old, new, 1)


def refused(name, body, needle, line_needle=None, runner="Rex"):
    """Exactly one finding, carrying `needle`, on the line containing
    `line_needle` - so the control proves the reason, not just the red."""
    rc, out = run_one(body, runner=runner)
    findings = [l for l in out.splitlines() if ": " in l and l.startswith(_tmp)]
    want_line = line_of(body, line_needle) if line_needle else None
    ok = (rc == 1 and len(findings) == 1 and needle in findings[0]
          and (want_line is None or (":%d:" % want_line) in findings[0])
          and "FINDINGS" in out)
    check(name, ok, "rc=%d out=%s" % (rc, out))


def write_config(name, cfg):
    path = os.path.join(_tmp, name)
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# === 1. The pass fixture passes, and the record line is printed.
rc, out = run_one(PASS)
check("the pass fixture exits 0", rc == 0, "rc=%d out=%s" % (rc, out))
check("a PASS names the runner, the builder and the commit",
      "PASS " in out and "run by Rex, builder Ada, on " in out, out)
check("a PASS prints the row to record in section 6",
      "record in its section 6: | Rex | " in out and out.rstrip().endswith("Z |"), out)

# === 2. The runner is the builder: refused, case-insensitively.
refused("runner == builder is refused (case-insensitive)", PASS,
        "the runner (ada) is the builder", "| Builder | Ada |", runner="ada")

# === 3. An empty item is refused.
refused("an empty Evidence cell is refused",
        mutate("| Sort the cart by price | DONE | `e2e/cart-sort.spec.ts:12` |",
               "| Sort the cart by price | DONE |  |"),
        "empty Evidence", "| Sort the cart by price | DONE |")
refused("an empty Plan item is refused",
        mutate("| T2 | DONE |", "|  | DONE |"), "empty Plan item", "[14 - item]")
refused("an all-empty row is refused",
        mutate("| 12 - sort sheet, empty state | Dana | NO DESIGN | %s1000000000000003 |" % CHAT,
               "|  |  |  |  |"), "empty row in 1c", "|  |  |  |  |")

# === 4. Evidence must be a path or a URL, and a path must open.
refused("evidence with no path or URL is refused",
        mutate("| 7 | DONE | `docs/plan.md` |", "| 7 | DONE | it is complete |"),
        "no evidence a reviewer can open", "| 7 | DONE |")
refused("a repo-relative path that does not exist is refused",
        mutate("`e2e/cart-sort.spec.ts:12`", "`e2e/gone.spec.ts:12`"),
        "`e2e/gone.spec.ts:12` cannot be opened: No such file", "gone.spec.ts")
refused("an absolute path that does not exist is refused",
        mutate("`ABS_EVIDENCE`", "`/nonexistent/check-checklist/verdict.txt`"),
        "cannot be opened", "| 12 - cart, default |")
refused("a Markdown link resolves from the checklist's directory, not the root",
        mutate("[plan](../plan.md)", "[plan](docs/plan.md)"),
        "`docs/plan.md` cannot be opened", "[plan](docs/plan.md)")
if os.geteuid() != 0:
    unreadable = os.path.join(_tmp, "outside", "unreadable.txt")
    with open(unreadable, "w") as f:
        f.write("x")
    os.chmod(unreadable, 0)
    refused("a path that exists but cannot be read is refused (opened, not stat'd)",
            mutate("`ABS_EVIDENCE`", "`%s`" % unreadable), "Permission denied",
            "| 12 - cart, default |")

# === 5. Closed vocabularies.
refused("a status outside the section's vocabulary is refused",
        mutate("| Sort the cart by price | DONE |", "| Sort the cart by price | finished |"),
        "Status `finished` is not one of: DONE, TODO", "| finished |")
refused("TODO is refused",
        mutate("| 1 | DONE |", "| 1 | TODO |"), "TODO: not done", "| 1 | TODO |")
refused("a qualified PASS is not a PASS",
        mutate("| PASS | `ABS_EVIDENCE` |", "| PASS (header only) | `ABS_EVIDENCE` |"),
        "qualifies PASS", "PASS (header only)")
refused("INCONCLUSIVE without a waiver is refused",
        mutate("| PASS | `ABS_EVIDENCE` |", "| INCONCLUSIVE | `ABS_EVIDENCE` |"),
        "INCONCLUSIVE is not a pass", "| INCONCLUSIVE |")
refused("FAIL is refused",
        mutate("| PASS | `ABS_EVIDENCE` |", "| FAIL | `ABS_EVIDENCE` |"),
        "fix the screen and re-run", "| FAIL |")
refused("WAIVED by a name off the allow-list is refused",
        mutate("WAIVED by Olive", "WAIVED by Mallory"),
        "waived by `Mallory`, who is not on the waiver allow-list (Olive, Tess, Dana)",
        "WAIVED by Mallory")
rc, out = run_one(mutate("WAIVED by Olive", "WAIVED by olive"))
check("a waiver name matches the allow-list case-insensitively", rc == 0, out)
refused("a PASS with no frame link is refused",
        mutate("| 12 - cart, default | [12 - cart](https://design.example.com/file/example?node=12) | PASS |",
               "| 12 - cart, default | none | PASS |"),
        "PASS needs the frame it was checked against", "| 12 - cart, default | none |")
refused("a 1b frame with no design-file link is refused",
        mutate("| [14 - item](https://design.example.com/file/example?node=14) | T2 |",
               "| 14 - item | T2 |"),
        "Frame needs the frame's name as a link", "| 14 - item | T2 |")

# === 6. Section 5 is read against SKILL.md's rule table.
refused("a rule with no row is refused",
        mutate("| 7 | DONE | `docs/plan.md` |\n", ""), "rule 7 has no row in 5",
        "## 5. Definition-of-done gates")
refused("a rule number outside the table is refused",
        mutate("| 7 | DONE | `docs/plan.md` |\n",
               "| 7 | DONE | `docs/plan.md` |\n| 9 | DONE | `docs/plan.md` |\n"),
        "rule 9 is not in the definition of done's rule table", "| 9 | DONE |")

# === 6b. Section 5's presentation to the requester: read by its label, its
# evidence held to the config's checklist.permalink_pattern.
PRES = ("| 6 - presented to the requester | DONE | "
        "%s1000000000000016?thread=1000000000000011 |" % CHAT)


def pres(status, evidence):
    return "| 6 - presented to the requester | %s | %s |" % (status, evidence)


refused("a missing presentation row is refused",
        mutate(PRES + "\n", ""), "5 has no `6 - presented to the requester` row",
        "## 5. Definition-of-done gates")
refused("a TODO presentation row is refused",
        mutate(PRES, PRES.replace("| DONE |", "| TODO |")), "TODO: not done",
        "| 6 - presented to the requester | TODO |")
for what, ev in [("a URL that is not a chat permalink",
                  "https://design.example.com/file/example?node=12"),
                 ("a repo path that opens", "`docs/plan.md`"),
                 ("a chat conversation link, not a message", "https://chat.example.com/feature-thread"),
                 ("a permalink with a trailing extra (a full match is owed)",
                  "%s1000000000000016/extra" % CHAT)]:
    refused("a DONE presentation whose evidence is %s is refused" % what,
            mutate(PRES, pres("DONE", ev)), "is not a chat message permalink",
            "| 6 - presented to the requester |")
rc, out = run_one(mutate(PRES, pres("DONE", "[the presentation](%s1000000000000016)" % CHAT)))
check("a permalink as a Markdown link, with no thread query, passes", rc == 0, out)
refused("an N/A presentation while the header names screens is refused",
        mutate(PRES, pres("N/A", "nothing to show")), "is N/A while the header names screens",
        "| 6 - presented to the requester | N/A |")
rc, out = run_one(mutate(PRES, pres("N/A", "the feature has no screen"),
                         mutate("| Screens | 12, 14 |", "| Screens | none |")))
check("an N/A presentation passes when the header's Screens is none", rc == 0, out)
refused("an AFTER HAND-OFF presentation is refused",
        mutate(PRES, pres("AFTER HAND-OFF", "the feature's thread")),
        "is AFTER HAND-OFF: the presentation comes before the hand-off",
        "| 6 - presented to the requester | AFTER HAND-OFF |")
# The pattern is the config's, not the script's: the same fixture is refused
# under a config whose transport writes permalinks differently.
other = load_json(CONFIG)
other["checklist"]["permalink_pattern"] = r"^https://other\.example\.org/msg/[0-9]+$"
other_cfg = write_config("other-transport.json", other)
root = repo({CL: PASS})
rc, out = run([os.path.join(root, CL)], config=other_cfg)
check("the permalink pattern is read from the config (another transport's refuses the fixture)",
      rc == 1 and "is not a chat message permalink" in out
      and "other\\.example\\.org" in out, out)

# === 7. Commits, section 6, the header and the commit state.
refused("a ruling's commit that does not resolve is refused",
        mutate("`COMMIT_SHA`", "`deadbeefdeadbeef`"), "does not resolve to a commit",
        "deadbeefdeadbeef")
refused("section 6 recording the builder is refused",
        mutate("| | | |\n", "| Ada | COMMIT_SHA | 2026-10-25T10:00Z |\n"),
        "6 records the builder (Ada)", "| Ada | COMMIT_SHA |")
rc, out = run_one(mutate("| | | |\n", "| Rex | COMMIT_SHA | 2026-10-25T10:00Z |\n"))
check("a filled section 6 by a non-builder passes", rc == 0, out)
refused("a slug that does not match the file name is refused",
        mutate("| Slug | example-feature |", "| Slug | other-feature |"),
        "does not match the file name", "| Slug | other-feature |")
rc, out = run_one(PASS, commit=False)
check("uncommitted changes to the checklist are refused",
      rc == 1 and "uncommitted changes" in out, out)

# === 8. The template parses, and a fresh copy is refused with findings - not 2.
rc, out = run_one(open(TEMPLATE).read())
check("a fresh copy of the template exits 1 (findings), not 2",
      rc == 1 and "TODO: not done" in out and "NO VERDICT" not in out, out)
check("the template carries the presentation row the checker reads by its label",
      "has no `6 - presented to the requester` row" not in out, out)

# === 9. Exit 2: nothing malformed is ever judged.
rc, out = run_one(mutate("## 4. Pixel verdicts", "## Pixel verdicts"))
check("a missing section is NO VERDICT (2)", rc == 2 and "missing section(s): 4" in out, out)
rc, out = run_one(mutate("| Screen and state | Frame | Verdict | Evidence |",
                         "| Screen and state | Frame | Result | Evidence |"))
check("a renamed column is NO VERDICT (2)", rc == 2 and "has columns" in out, out)
rc, out = run_one(mutate("| 1 | DONE |", "| 1 | DONE | extra |"))
check("a row with the wrong cell count is NO VERDICT (2)", rc == 2 and "cells" in out, out)
rc, out = run([os.path.join(_tmp, "does-not-exist.md")])
check("an unreadable file is NO VERDICT (2), not 0", rc == 2 and "unreadable" in out, out)
outside = os.path.join(_tmp, "nogit", "example-feature.md")
os.makedirs(os.path.dirname(outside))
with open(outside, "w") as f:
    f.write(PASS)
rc, out = run([outside], cwd=os.path.dirname(outside))
check("a checklist outside a git checkout is NO VERDICT (2)",
      rc == 2 and "not inside a git checkout" in out, out)
root = repo({CL: PASS})
rc, out = run([os.path.join(root, CL)], runner=None)
check("no establishable runner identity is NO VERDICT (2)",
      rc == 2 and "who is running the checker" in out, out)
bad = write_config("bad-config.json", {"checklist": {"dir": "docs/checklists"}})
rc, out = run([os.path.join(root, CL)], config=bad)
check("a config with no waiver list is NO VERDICT (2)",
      rc == 2 and "checklist.waivers" in out, out)
no_pattern = load_json(CONFIG)
del no_pattern["checklist"]["permalink_pattern"]
rc, out = run([os.path.join(root, CL)], config=write_config("no-pattern.json", no_pattern))
check("a config with no permalink pattern is NO VERDICT (2)",
      rc == 2 and "no checklist.permalink_pattern" in out, out)
broken = load_json(CONFIG)
broken["checklist"]["permalink_pattern"] = "^https://chat\\.example\\.com/(unclosed$"
rc, out = run([os.path.join(root, CL)], config=write_config("broken-pattern.json", broken))
check("a permalink pattern that does not compile is NO VERDICT (2)",
      rc == 2 and "does not compile" in out, out)
copy = os.path.join(_tmp, "skillcopy")
os.makedirs(copy)
shutil.copy(SCRIPT, copy)
with open(os.path.join(copy, "SKILL.md"), "w") as f:
    f.write("# a SKILL.md with no rule table\n")
rc, out = run([os.path.join(root, CL)], script=os.path.join(copy, "check_checklist.py"))
check("SKILL.md with no rule table is NO VERDICT (2)", rc == 2 and "no rule numbers" in out, out)
rc, out = run([], config=None)
check("no argument is a usage error (2)", rc == 2 and "usage" in out.lower(), out)
empty = os.path.join(root, "docs", "empty")
os.makedirs(empty)
rc, out = run([empty])
check("a directory holding no checklist is NO VERDICT (2), never a pass",
      rc == 2 and "checked nothing" in out, out)

# === 9b. The default config: the install's, resolved through fleetlib.
rc, out = run([os.path.join(root, CL)], config=None)
check("with no --config, the install's config resolves through fleetlib (the fixture install)",
      rc == 0 and "PASS " in out, out)
link = os.path.join(_tmp, "skill-link")
os.symlink(HERE, link)
rc, out = run([os.path.join(root, CL)], config=None,
              script=os.path.join(link, "check_checklist.py"))
check("run through a linked skill DIRECTORY (how fleet link installs it), fleetlib is found by realpath",
      rc == 0 and "PASS " in out, out)
# A link to the script FILE, in a directory with no SKILL.md: only realpath
# finds the rule table. --config is given so this case measures SKILL.md alone.
file_link_dir = os.path.join(_tmp, "script-link")
os.makedirs(file_link_dir)
os.symlink(SCRIPT, os.path.join(file_link_dir, "check_checklist.py"))
rc, out = run([os.path.join(root, CL)], script=os.path.join(file_link_dir, "check_checklist.py"))
check("run through a link to the script FILE, SKILL.md's rule table is found by realpath",
      rc == 0 and "PASS " in out, out)
no_install = os.path.join(_tmp, "no-install")
os.makedirs(no_install)
rc, out = run([os.path.join(root, CL)], config=None, context_root=no_install)
check("with no --config and no install manifest, it is NO VERDICT (2), never a pass",
      rc == 2 and "cannot resolve the install's config.json" in out and "PASS" not in out, out)
rc, out = run([os.path.join(root, CL)], config=None, context_root=no_install,
              script=os.path.join(copy, "check_checklist.py"))
check("a stray copy with no fleet tree above it is NO VERDICT (2) without --config",
      rc == 2 and "NO VERDICT" in out and "PASS" not in out, out)

# === 9c. The example config: same keys as the fixture install's, and loadable.


def leaves(obj, pre=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not k.startswith("_"):
                yield from leaves(v, pre + (k,))
    else:
        yield ".".join(pre)


example = load_json(EXAMPLE_CONFIG)
fixture_cfg = load_json(CONFIG)
check("config.example.json and the fixture install's config.json carry the same keys",
      sorted(leaves(example)) == sorted(leaves(fixture_cfg)),
      "example only: %s; fixture only: %s" % (
          sorted(set(leaves(example)) - set(leaves(fixture_cfg))),
          sorted(set(leaves(fixture_cfg)) - set(leaves(example)))))
# Loaded in-process for load_config alone; no bytecode is written beside the
# script, which in a host fleet checkout is a read-only tree.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("check_checklist", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    _, example_dir, example_link, _ = mod.load_config(EXAMPLE_CONFIG)
    loads = True
except mod.NoVerdict as e:
    loads, example_dir, example_link = str(e), None, None
check("config.example.json loads as a checker config", loads is True, str(loads))
if example_link is not None:
    slack_message = "https://acme.slack.com/archives/CABCDEFGH/p1000000000000001"
    check("the example pattern is the Slack message permalink shape its comment says",
          bool(example_link.fullmatch(slack_message))
          and bool(example_link.fullmatch(slack_message + "?thread_ts=1000000000.000001"))
          and not example_link.fullmatch("https://acme.slack.com/archives/CABCDEFGH"),
          example_link.pattern)

# === 9d. No design file: figma.file_key null lifts the design sections, and
# nothing else; an ABSENT key lifts nothing.
no_design = load_json(CONFIG)
no_design["figma"]["file_key"] = None
NO_DESIGN_CFG = write_config("no-design.json", no_design)


def emptied(body, heading, next_heading):
    """`body` with the data rows of the table under `heading` removed."""
    start = body.index(heading)
    end = body.index(next_heading)
    lines = body[start:end].split("\n")
    kept, seen_sep = [], False
    for l in lines:
        if l.startswith("|---"):
            seen_sep = True
            kept.append(l)
        elif seen_sep and l.startswith("|"):
            continue
        else:
            kept.append(l)
    return body[:start] + "\n".join(kept) + body[end:]


BARE = PASS
for h, nxt in (("### 1a. ", "### 1b. "), ("### 1b. ", "### 1c. "), ("### 1c. ", "## 2. "),
               ("## 4. ", "## 4b. ")):
    BARE = emptied(BARE, h, nxt)
BARE = BARE.replace(
    "| 2026-10-22 | Dana | [ruling](https://chat.example.com/feature-thread/m/1000000000000005) | "
    "[12 - cart](https://design.example.com/file/example?node=12) | `COMMIT_SHA` | RE-FROZEN | "
    "https://chat.example.com/feature-thread/m/1000000000000006 |\n", "")
assert BARE != PASS and "| Contradictions and removals list |" not in BARE and "| 12 - cart, default |" not in BARE
root = repo({CL: BARE})
rc, out = run([os.path.join(root, CL)], config=NO_DESIGN_CFG)
check("no design file: empty 1a, 1b, 1c and 4 pass, with a NOTE saying so",
      rc == 0 and "PASS " in out and "NOTE: figma.file_key is null" in out, out)
rc, out = run([os.path.join(root, CL)])
found = [l for l in out.splitlines() if l.startswith(root)]
check("with a design file, the same empty sections are refused, exactly three findings",
      rc == 1 and len(found) == 3 and "1a has no rows" in out
      and "no frames in 1b and no screens in 1c" in out and "4 has no rows" in out
      and "NOTE:" not in out, out)
root = repo({CL: mutate("| Contradictions and removals list | DONE |", "| Contradictions and removals list | TODO |")})
rc, out = run([os.path.join(root, CL)], config=NO_DESIGN_CFG)
check("no design file: a row that IS there is still checked (a TODO in 1a is refused)",
      rc == 1 and "TODO: not done" in out, out)
root = repo({CL: mutate(PRES + "\n", "", BARE)})
rc, out = run([os.path.join(root, CL)], config=NO_DESIGN_CFG)
check("no design file: the presentation row is still owed, with the videos only",
      rc == 1 and "has no `6 - presented to the requester` row" in out
      and "a video of the feature per platform (N/A" in out and "diff maps" not in out, out)
# Null lifts the design sections and nothing else: the sections it does not
# lift stay owed under the null config, each with its one finding.
for what, body, needle in [
        ("an empty section 2 (scope)", emptied(BARE, "## 2. ", "## 3. "),
         "2 has no rows: a feature has at least one scope item"),
        ("a missing section 4b (the bug hunt)",
         BARE.replace(BARE[BARE.index("## 4b. "):BARE.index("## 5. Definition-of-done gates")], ""),
         "no section 4b: the bug hunt")]:
    root = repo({CL: body})
    rc, out = run([os.path.join(root, CL)], config=NO_DESIGN_CFG)
    found = [l for l in out.splitlines() if l.startswith(root)]
    check("no design file lifts nothing else: %s is still refused" % what,
          rc == 1 and len(found) == 1 and needle in found[0], out)
absent = load_json(CONFIG)
del absent["figma"]["file_key"]
root = repo({CL: BARE})
rc, out = run([os.path.join(root, CL)], config=write_config("no-file-key.json", absent))
check("a config with no figma.file_key at all is NO VERDICT (2): an absent key relaxes nothing",
      rc == 2 and "has no figma.file_key" in out and "PASS" not in out, out)
blank = load_json(CONFIG)
blank["figma"]["file_key"] = "  "
rc, out = run([os.path.join(root, CL)], config=write_config("blank-file-key.json", blank))
check("a blank figma.file_key is NO VERDICT (2), not read as no design file",
      rc == 2 and "neither a design file's key nor null" in out, out)

# === 10. Several files in one run: per-file verdicts, the worst exit wins.
FAILING = mutate("| 1 | DONE |", "| 1 | TODO |").replace("example-feature", "failing-feature")
MALFORMED = mutate("## 4. Pixel verdicts", "## Pixel verdicts").replace(
    "example-feature", "malformed-feature")
root = repo({CL: PASS, "docs/checklists/failing-feature.md": FAILING})
rc, out = run([os.path.join(root, CL), os.path.join(root, "docs/checklists/failing-feature.md")])
check("one passing + one failing file: exit 1, both reported",
      rc == 1 and "PASS " in out and "FINDINGS " in out and "1 passed, 1 with findings" in out, out)
rc, out = run([os.path.join(root, "docs/checklists")])
check("a directory checks every .md in it",
      rc == 1 and "2 checked" in out and "example-feature.md" in out and "failing-feature.md" in out, out)
root = repo({CL: PASS, "docs/checklists/failing-feature.md": FAILING,
             "docs/checklists/malformed-feature.md": MALFORMED})
rc, out = run([os.path.join(root, "docs/checklists")])
check("findings + no verdict in one run: exit 2 (2 beats 1), each reported",
      rc == 2 and "FINDINGS " in out and "NO VERDICT " in out and "PASS " in out, out)

# === 11. --expect: the release candidate's changelist.
rc, out = run([os.path.join(root, "docs/checklists"), "--expect", "example-feature,missing-feature"])
check("--expect: a changelist feature with no checklist is MISSING (exit 1), not a skip",
      rc == 1 and "MISSING missing-feature" in out and "PASS " in out, out)
check("--expect: files in the directory that are not expected are not checked",
      "failing-feature" not in out and "malformed-feature" not in out, out)
rc, out = run([os.path.join(root, "docs/checklists"), "--expect", "example-feature"])
check("--expect: every expected checklist present and passing exits 0", rc == 0, out)

# === 12. Section 4b: the bug hunt by an agent that did not build it.
RUN = "| Hugo | `COMMIT_SHA` | section 2 | 2026-10-24T09:00Z |"
F1 = "| 1 | The sort sheet clips its longest label | FIXED in COMMIT_SHA |"
F2 = "| 2 | An empty cart shows no sort hint | NOT A BUG: the design draws no hint for the empty state (1c) |"
F3 = "| 3 | The sort lags on a 400-item cart | WAIVED by Dana |"
URL12 = CHAT + "1000000000000012"
FIND_ROWS = PASS[PASS.index(F1):PASS.index("## 5. Definition-of-done gates")].rstrip("\n") + "\n"
HUNT_SECTION = PASS[PASS.index("## 4b. "):PASS.index("## 5. Definition-of-done gates")]
NONE_ROW = "| 1 | NONE | - | %s |\n" % URL12

refused("a missing section 4b is a finding (exit 1), not NO VERDICT",
        mutate(HUNT_SECTION, ""), "no section 4b: the bug hunt", "## 4. Pixel verdicts")
refused("an empty Hunter is refused", mutate(RUN, RUN.replace("| Hugo |", "|  |")),
        "empty Hunter", "section 2 | 2026-10-24T09:00Z")
refused("a hunter who is the builder is refused (same comparison as the runner's)",
        mutate(RUN, RUN.replace("| Hugo |", "| ada |")),
        "the hunter (ada) is the builder", "| ada | `COMMIT_SHA` |")
refused("a build commit that does not resolve is refused",
        mutate(RUN, RUN.replace("`COMMIT_SHA`", "`deadbeefdeadbeef`")),
        "Build (commit) deadbeefdeadbeef does not resolve", "deadbeefdeadbeef")
refused("a build given as a URL is refused (ancestry needs a sha)",
        mutate(RUN, RUN.replace("`COMMIT_SHA`", "https://git.example.com/app/commit/abc1234")),
        "is not a commit sha", "git.example.com/app/commit")
refused("a build that is not an ancestor of the hand-off commit is refused",
        mutate(RUN, RUN.replace("`COMMIT_SHA`", "`SIDE_SHA`")),
        "is neither the hand-off commit", "| Hugo | `SIDE_SHA` |")
refused("the hand-off commit recorded in 6 is the one the build is held to",
        mutate("| | | |\n", "| Rex | COMMIT_SHA | 2026-10-25T10:00Z |\n",
               mutate(RUN, RUN.replace("`COMMIT_SHA`", "`SIDE_SHA`"))),
        "is neither the hand-off commit", "| Hugo | `SIDE_SHA` |")
refused("a scope that does not point at section 2 is refused",
        mutate(RUN, RUN.replace("| section 2 |", "| the plan |")),
        "does not point at section 2", "| the plan |")
rc, out = run_one(mutate(RUN, RUN.replace("| section 2 |", "| \u00a72 |")))
check("a scope written with the section sign passes", rc == 0, out)
refused("a Run at that is not ISO 8601 UTC is refused",
        mutate(RUN, RUN.replace("2026-10-24T09:00Z", "yesterday")),
        "Run at `yesterday` is not ISO 8601 UTC", "| yesterday |")
refused("run evidence that does not open is refused (the shared evidence rule)",
        mutate(RUN + " " + URL12, RUN + " `docs/hunt-notes.md`"),
        "`docs/hunt-notes.md` cannot be opened", "docs/hunt-notes.md")
refused("an empty run table is refused",
        mutate(RUN + " " + URL12 + " |\n", ""), "4b's run table is empty",
        "## 4b. Bug hunt")
refused("a run table with two rows is refused",
        mutate(RUN + " " + URL12 + " |\n", (RUN + " " + URL12 + " |\n") * 2),
        "4b's run table holds 2 rows", "## 4b. Bug hunt")
refused("an empty findings table is refused - it reads as a hunt never run",
        mutate(FIND_ROWS, ""), "4b's findings table is empty", "## 4b. Bug hunt")
rc, out = run_one(mutate(FIND_ROWS, NONE_ROW))
check("a hunt that found nothing - one NONE row - passes", rc == 0, out)
refused("a NONE row beside real findings is refused",
        mutate(FIND_ROWS, FIND_ROWS + NONE_ROW.replace("| 1 |", "| 4 |")),
        "a NONE row is the only row", "| 4 | NONE |")
refused("a NONE row with a disposition is refused",
        mutate(FIND_ROWS, NONE_ROW.replace("| - |", "| FIXED in COMMIT_SHA |")),
        "a NONE row's Disposition is `-`", "| 1 | NONE |")
refused("a FIXED commit that does not resolve is refused",
        mutate(F1, F1.replace("FIXED in COMMIT_SHA", "FIXED in deadbeefdeadbeef")),
        "FIXED in deadbeefdeadbeef does not resolve", "FIXED in deadbeefdeadbeef")
refused("a FIXED commit that is not an ancestor of the hand-off commit is refused",
        mutate(F1, F1.replace("FIXED in COMMIT_SHA", "FIXED in SIDE_SHA")),
        "is neither the hand-off commit", "FIXED in SIDE_SHA")
refused("a waiver by a name off the allow-list is refused (the shared waiver rule)",
        mutate(F3, F3.replace("WAIVED by Dana", "WAIVED by Mallory")),
        "waived by `Mallory`, who is not on the waiver allow-list", "WAIVED by Mallory")
refused("NOT A BUG with no reason is refused",
        mutate(F2, F2.replace("NOT A BUG: the design draws no hint for the empty state (1c)", "NOT A BUG:")),
        "NOT A BUG needs one after the colon", "| NOT A BUG: |")
refused("a disposition outside the vocabulary is refused",
        mutate(F1, F1.replace("FIXED in COMMIT_SHA", "fixed it")),
        "Disposition `fixed it` is not one of: FIXED in <commit>, NOT A BUG: <reason>, WAIVED by <name>, TODO",
        "| fixed it |")
refused("a TODO disposition is refused (the shared TODO rule)",
        mutate(F1, F1.replace("FIXED in COMMIT_SHA", "TODO")), "TODO: not done",
        "The sort sheet clips its longest label | TODO")
refused("a finding with no evidence is refused (the shared empty-cell rule)",
        mutate(F3 + " %s1000000000000015 |" % CHAT, F3 + "  |"),
        "empty Evidence", "WAIVED by Dana |  |")
rc, out = run_one(mutate("| # | Finding | Disposition | Evidence |", "| # | Finding | Outcome | Evidence |"))
check("a renamed 4b column is NO VERDICT (2)", rc == 2 and "has columns" in out, out)
rc, out = run_one(mutate(FIND_ROWS, "").replace("| # | Finding | Disposition | Evidence |\n|---|---|---|---|\n", ""))
check("a section 4b holding one table is NO VERDICT (2)", rc == 2 and "holds 1 tables, expected 2" in out, out)

# === 13. --served: the build served to the tester is the build the evidence is for.
HANDED = mutate("| | | |\n", "| Rex | COMMIT_SHA | 2026-10-25T10:00Z |\n")
OTHER_CL = "docs/checklists/other-feature.md"
OTHER = HANDED.replace("example-feature", "other-feature")


def served(root, target, names=(CL,)):
    """(rc, out, the findings lines) of a --served run over `names` in `root`."""
    rc, out = run([os.path.join(root, n) for n in names] + ["--served", target])
    return rc, out, [l for l in out.splitlines() if l.startswith(root) and ": " in l]


root = repo({CL: HANDED})
evid = g(root, "rev-list", "--max-parents=0", "HEAD")
wt = os.path.join(_tmp, "serve-at-handoff")
g(root, "worktree", "add", "-q", "--detach", wt, evid)
rc, out, _ = served(root, wt)
check("--served: a serve whose HEAD IS the hand-off commit passes, with its SERVED line",
      rc == 0 and ("SERVED %s at %s: contains the hand-off commit(s) %s; nothing but "
                   "checklists changed since" % (wt, evid, evid)) in out, out)
head = g(root, "rev-parse", "HEAD")
rc, out, _ = served(root, root)
check("--served: a checklist-only commit after the hand-off passes",
      rc == 0 and ("SERVED %s at %s: contains the hand-off commit(s) %s; nothing but "
                   "checklists changed since" % (root, head, evid)) in out, out)

root = repo({CL: mutate("| | | |\n", "| Rex | SIDE_SHA | 2026-10-25T10:00Z |\n")})
side = g(root, "rev-parse", "side")
head = g(root, "rev-parse", "HEAD")
rc, out, found = served(root, root)
check("--served: a HEAD that does not contain the hand-off commit is refused, naming both",
      rc == 1 and len(found) == 1 and "does not contain the hand-off commit %s" % side[:12] in found[0]
      and head[:12] in found[0] and "SERVED" not in out, out)

root = repo({CL: HANDED, "src/fix.ts": "export const fix = 1;\n"})
rc, out, found = served(root, root)
check("--served, one checklist: code changed after the hand-off is refused, listing it",
      rc == 1 and len(found) == 1 and "src/fix.ts" in found[0]
      and "outside docs/checklists/" in found[0] and "SERVED" not in out, out)

root = repo({CL: HANDED, OTHER_CL: OTHER, "src/fix.ts": "export const fix = 1;\n"})
rc, out, _ = served(root, root, (CL, OTHER_CL))
check("--served, several checklists: only the contains rule applies (the stated limit)",
      rc == 0 and "SERVED %s at " % root in out
      and "nothing but checklists" not in out, out)

root = repo({CL: PASS})
rc, out, found = served(root, root)
check("--served: a checklist with no recorded hand-off is refused",
      rc == 1 and len(found) == 1 and "section 6 records no hand-off commit" in found[0], out)

rc, out = run([os.path.join(root, CL), "--served", os.path.dirname(outside)])
check("--served: a path that is not a git worktree is NO VERDICT (2)",
      rc == 2 and "is not a git worktree" in out and "SERVED" not in out, out)
rc, out = run([os.path.join(root, CL), "--served", os.path.join(_tmp, "no-such-worktree")])
check("--served: a path that does not exist is NO VERDICT (2)",
      rc == 2 and "is not a git worktree" in out, out)
unborn = os.path.join(_tmp, "unborn")
os.makedirs(unborn)
g(unborn, "init", "-q")
rc, out = run([os.path.join(root, CL), "--served", unborn])
check("--served: a worktree whose HEAD does not resolve is NO VERDICT (2)",
      rc == 2 and "has no HEAD commit that resolves" in out, out)

# === 14. The hand-off replay is refused, with exactly its findings.
REPLAY = fixture("handoff-replay.md")
root = repo({"docs/checklists/handoff-replay.md": REPLAY})
rc, out = run([os.path.join(root, "docs/checklists/handoff-replay.md")])
findings = [l for l in out.splitlines() if l.startswith(root)]
print("\n--- the hand-off replay, as the checker reports it ---")
print(out.replace(root + "/", ""), end="")
print("--- end ---\n")
expected = [
    ("[Summary slide]", "empty Plan item"),
    ("| Home - header |", "qualifies PASS"),
    ("| Item - own listing, manage sheet |", "INCONCLUSIVE is not a pass"),
    ("| Item - three-dot menu |", "empty Verdict"),
    ("| Item - three-dot menu |", "empty Evidence"),
    ("| Item - share sheet |", "empty Verdict"),
    ("| Item - share sheet |", "empty Evidence"),
    ("| Summary slide |", "empty Verdict"),
    ("| Summary slide |", "empty Evidence"),
    ("## 4b. Bug hunt", "4b's run table is empty"),
    ("## 4b. Bug hunt", "4b's findings table is empty"),
    ("## 5. Definition-of-done gates", "has no `6 - presented to the requester` row"),
]
check("the hand-off replay exits 1", rc == 1, out)
for needle, msg in expected:
    ln = line_of(REPLAY, needle)
    check("replay: line %d (%s) carries '%s'" % (ln, needle.strip("|[] "), msg),
          any((":%d:" % ln) in f and msg in f for f in findings), out)
check("replay: no finding beyond those %d" % len(expected), len(findings) == len(expected),
      "\n".join(findings))

shutil.rmtree(_tmp, ignore_errors=True)

print()
if _failures:
    print("FAILED: %d of %d check(s): %s" % (len(_failures), _count[0], ", ".join(_failures)))
    sys.exit(1)
print("ALL %d CHECKS PASSED" % _count[0])
