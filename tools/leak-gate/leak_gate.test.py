#!/usr/bin/env python3
"""leak_gate.test.py - teeth for tools/leak-gate/leak_gate.py and for the
pre-commit and pre-push hooks that call it.

Run: python3 tools/leak-gate/leak_gate.test.py   (tests/run-all.sh runs it)

Every case drives the REAL leak_gate.py (copied with its rule files, and the
lib/fleetlib/ it imports from its own repository, into a throwaway git
repository, so the copy under test is byte-identical to the committed one) as
a subprocess with a scrubbed environment: no inherited GIT_*
variable, a fixture HOME, a fixture global git config, and a host config path
that does not exist unless the case creates one. Nothing here reads this
machine's real host config, install manifest or deny list.

THE SHAPE OF EVERY POSITIVE CONTROL: the bad input is shown RED (the finding
named, exit 1) AND the fixed input GREEN (exit 0) through the same scope, and
every output is checked for the deny value. A control that only showed red
could be a gate that refuses everything; one that only showed green could be a
gate that checks nothing.

WHAT EACH GROUP PROVES, and what breaks if it is deleted:
  * DenyScopes - a synthetic deny entry is caught through --staged, --range
    (content, message, author), --message, --identity, --ref, --tree, a binary
    file's metadata chunk (plain tEXt, compressed zTXt, UTF-16), a file NAME
    and a symlink TARGET, and no output carries the value. Delete one and that
    path can stop being scanned with nothing red. A --tree directory the walk
    cannot list is exit 3, and the same tree made readable shows the value the
    fault was hiding (skipped only for a user who can list a mode-000
    directory, where no unreadable directory exists).
  * Allow - a placeholder Slack id passes ONLY through its allow.txt entry: the same line
    is shown RED with no entry (so the pass is the entry's doing, not a blind
    pattern), and RED again when the line changes. An allow entry never
    silences a deny hit. A range is judged by the allow.txt its TIP commit
    carries: GREEN from a checkout whose working tree holds the older list,
    and RED for an entry only the working tree holds.
  * AiIdentity - an AI tool's identity (its address domain, its bare name) is
    `ai-identity` as author, committer and tagger, through --identity and
    through --range --ci (CI's leak job); a person called Claude and a
    look-alike domain are decoys that must stay GREEN.
  * DenyHalf - the fail-closed rule: a fleet host with no readable deny list is
    exit 3; upstream.deny_list = null and a machine with no host config print
    their skip lines; the scanned tree's own manifest is never consulted; --ci
    never reads the list.
  * DenyForms - sub/word/case/re semantics, normalization, and invalid entries
    refused by line number without printing their text.
  * PublicPatterns - one positive per class, and the e-mail exclusions.
  * Gitleaks - a finding is reported without the secret; a missing, wrong
    version or crashing gitleaks is exit 3, never a pass; the gate passes
    --ignore-gitleaks-allow, its own --config and the `dir` subcommand
    (asserted on the argv, because a default ruleset cannot show a flag's
    absence); and the REAL pinned gitleaks finds a secret through --tree,
    --staged, --range and --message - and still finds it, through --staged
    and --range, while each mechanism that blinds gitleaks' own git mode is
    planted: a `-diff` or `binary` attribute (tree, info/attributes), a
    .gitleaks.toml in the scanned tree (untracked, committed, at a --tree
    top), color.ui / color.diff = always. Each of those cases first runs
    gitleaks DIRECTLY and requires it to find nothing: that regime control is
    what makes the gate's finding the gate's doing. If it ever finds the
    secret (a new pinned gitleaks or git that renders differently), the
    planted mechanism no longer blinds anything, and the case fails with a
    `regime:` message: no verdict on the gate, and never a pass.
  * Hooks - real `git commit` and `git push` through .githooks: pre-commit
    refuses a staged value (from a subdirectory and from a linked worktree
    too), a fenced `git commit -- <path>` is judged on exactly what it
    commits, and pre-push refuses a --no-verify commit and a bad ref name even
    when it is the second ref of one push.

The deny value is synthetic and appears in no real list. Strings that would
trip a public pattern in THIS file are assembled at runtime, so the commit
gate passes this file on its own merits, not through allow.txt.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import zlib
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parents[2]
GATE_SRC = REPO / "tools" / "leak-gate"
LIB_SRC = REPO / "lib" / "fleetlib"
HOOKS_SRC = REPO / ".githooks"
HYGIENE_SRC = REPO / "tools" / "commit-hygiene"
PINNED = (GATE_SRC / "gitleaks.version").read_text().split()[0].lstrip("v")

TOKEN = "zorbl" + "edex"            # the synthetic deny value (word: entry, line 2)
CASE_TOKEN = "Quor" + "vane"        # a case: entry (line 3)
SUB_TOKEN = "plinth" + "wobble"     # a sub: entry (line 4)
RE_MARK = "snark" + "lefoot"        # matched by the re: entry (line 5)
DENY_TEXT = (
    "# fixture deny list - synthetic values only\n"
    f"word:{TOKEN}\n"
    f"case:{CASE_TOKEN}\n"
    f"sub:{SUB_TOKEN}\n"
    "re:snark" "le[f]oot-[0-9]+\n"
)
PLACEHOLDER_ID = "U0" + "EXAMPLE99"
INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u034f\u180e\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"))

FAKE_GITLEAKS = f'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ.get("FAKE_GITLEAKS_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps(args) + "\\n")
if args[:1] == ["version"]:
    print(os.environ.get("FAKE_GITLEAKS_VERSION", "{PINNED}"))
    sys.exit(0)
if os.environ.get("FAKE_GITLEAKS_CRASH"):
    print("fake crash", file=sys.stderr)
    sys.exit(1)
findings = json.loads(os.environ.get("FAKE_GITLEAKS_FINDINGS", "[]"))
with open(args[args.index("--report-path") + 1], "w") as fh:
    json.dump(findings, fh)
sys.exit(9 if findings else 0)
'''


def real_gitleaks() -> str:
    for cand in (shutil.which("gitleaks"), str(Path.home() / ".local" / "bin" / "gitleaks")):
        if cand and os.access(cand, os.X_OK):
            got = subprocess.run([cand, "version"], capture_output=True, text=True).stdout.strip()
            if got == PINNED:
                return cand
    raise AssertionError(f"the real gitleaks {PINNED} is required by this test and is not installed: "
                         "bash tools/leak-gate/install-gitleaks.sh ~/.local/bin")


def visible(text: str) -> str:
    return unicodedata.normalize("NFKC", text.translate(INVISIBLE)).translate(INVISIBLE).lower()


def png(chunks: list[tuple[bytes, bytes]]) -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + ctype + data
                + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + b"".join(chunk(t, d) for t, d in chunks)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))


def github_pat() -> str:
    rng = random.Random(20261106)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "gh" + "p_" + "".join(rng.choice(alphabet) for _ in range(36))


class Fixture:
    """A throwaway git repository holding a byte-identical copy of the gate."""

    def __init__(self, root: Path, hooks: bool = False):
        self.root = root
        self.repo = root / "repo"
        self.home = root / "home"
        self.home.mkdir()
        gate = self.repo / "tools" / "leak-gate"
        gate.mkdir(parents=True)
        for name in ("leak_gate.py", "patterns.txt", "gitleaks.version", "gitleaks.toml"):
            shutil.copy2(GATE_SRC / name, gate / name)
        # the gate imports fleetlib from the repository it sits in, as in any clone
        (self.repo / "lib" / "fleetlib").mkdir(parents=True)
        for p in LIB_SRC.glob("*.py"):
            if not p.name.endswith(".test.py"):
                shutil.copy2(p, self.repo / "lib" / "fleetlib" / p.name)
        (gate / "allow.txt").write_text("# fixture allow list\n")
        self.deny = root / "deny.txt"
        self.deny.write_text(DENY_TEXT)
        self.fake = root / "fake-gitleaks"
        self.fake.write_text(FAKE_GITLEAKS)
        self.fake.chmod(0o755)
        gitconfig = root / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Fixture Tester\n\temail = tester@example.com\n"
                             "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n")
        tmp = root / "tmp"
        tmp.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(tmp),
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "FLEET_HOST_CONFIG": str(root / "no-host.json"),
            "FLEET_LEAK_DENY_FILE": str(self.deny),
            "FLEET_GITLEAKS": str(self.fake),
        }
        self.git("init", "-q")
        if hooks:
            shutil.copytree(HOOKS_SRC, self.repo / ".githooks")
            shutil.copytree(HYGIENE_SRC, self.repo / "tools" / "commit-hygiene",
                            ignore=shutil.ignore_patterns("*.test.sh"))
        (self.repo / "README").write_text("fixture\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        if hooks:
            self.git("config", "core.hooksPath", ".githooks")

    def run(self, cmd, cwd=None, env=None, input_text=None):
        full = dict(self.env)
        full.update(env or {})
        for k in [k for k, v in full.items() if v is None]:
            del full[k]
        return subprocess.run(cmd, cwd=cwd or self.repo, env=full, capture_output=True, text=True,
                              input=input_text, stdin=None if input_text is not None else subprocess.DEVNULL)

    def git(self, *args, cwd=None, env=None, check=True):
        proc = self.run(["git", *args], cwd=cwd, env=env)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def gate(self, *args, cwd=None, env=None):
        proc = self.run([sys.executable, str(self.repo / "tools" / "leak-gate" / "leak_gate.py"), *args],
                        cwd=cwd, env=env)
        return proc.returncode, proc.stdout + proc.stderr

    def write(self, rel: str, data, mode: str = "w") -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
        return path


class Base(unittest.TestCase):
    hooks = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="leak-gate-test-")
        self.fx = Fixture(Path(self._tmp.name), hooks=self.hooks)

    def tearDown(self):
        self._tmp.cleanup()

    def fresh(self) -> Fixture:
        """A second, independent fixture inside this case's temporary directory."""
        return Fixture(Path(tempfile.mkdtemp(dir=self._tmp.name)), hooks=self.hooks)

    def assertMasked(self, out: str):
        for value in (TOKEN, CASE_TOKEN, SUB_TOKEN, RE_MARK):
            self.assertNotIn(value.lower(), visible(out), f"a deny value reached the output:\n{out}")

    def assertRed(self, result, *expect: str):
        rc, out = result
        self.assertEqual(rc, 1, f"expected exit 1 (finding), got {rc}:\n{out}")
        for e in expect:
            self.assertIn(e, out, f"expected {e!r} in:\n{out}")
        self.assertMasked(out)

    def assertGreen(self, result, *expect: str):
        rc, out = result
        self.assertEqual(rc, 0, f"expected exit 0 (clean), got {rc}:\n{out}")
        self.assertIn("clean. scanned:", out)
        for e in expect:
            self.assertIn(e, out, f"expected {e!r} in:\n{out}")
        self.assertMasked(out)

    def assertFault(self, result, *expect: str):
        rc, out = result
        self.assertEqual(rc, 3, f"expected exit 3 (fault), got {rc}:\n{out}")
        self.assertIn("no verdict", out)
        for e in expect:
            self.assertIn(e, out, f"expected {e!r} in:\n{out}")
        self.assertMasked(out)


class DenyScopes(Base):
    def test_staged_content(self):
        self.fx.write("notes.txt", f"line one\nsee {TOKEN} here\n")
        self.fx.git("add", "notes.txt")
        self.assertRed(self.fx.gate("--staged"), "notes.txt:2 deny#2")
        self.fx.write("notes.txt", "line one\nsee nothing here\n")
        self.fx.git("add", "notes.txt")
        self.assertGreen(self.fx.gate("--staged"))

    def test_staged_file_name(self):
        self.fx.write(f"docs/{TOKEN}-notes.txt", "plain\n")
        self.fx.git("add", "-A")
        self.assertRed(self.fx.gate("--staged"), "docs/[deny#2]-notes.txt:(path) deny#2")
        self.fx.git("mv", f"docs/{TOKEN}-notes.txt", "docs/notes.txt")
        self.assertGreen(self.fx.gate("--staged"))

    def test_staged_rename_scans_the_destination_not_the_source(self):
        self.fx.write("plain.txt", "x\n")
        self.fx.git("add", "plain.txt")
        self.fx.git("commit", "-q", "-m", "plain")
        self.fx.git("mv", "plain.txt", f"{TOKEN}.txt")
        self.assertRed(self.fx.gate("--staged"), "[deny#2].txt:(path) deny#2")
        self.fx.git("commit", "-q", "-m", "named")
        # renaming the leaking name away is the fix, and must not be refused for the old name
        self.fx.git("mv", f"{TOKEN}.txt", "plain.txt")
        self.assertIn("R", self.fx.git("diff", "--cached", "--name-status", "-M")[:1])
        self.assertGreen(self.fx.gate("--staged"))

    def test_range_annotated_tag_message_and_tagger(self):
        base = self.fx.git("rev-parse", "HEAD")
        self.fx.git("commit", "-q", "--allow-empty", "-m", "release")
        self.fx.git("tag", "-a", "v9.9.9", "-m", f"notes naming {TOKEN}")
        self.assertRed(self.fx.gate("--range", f"{base}..v9.9.9"), ":(tag message):1 deny#2")
        self.fx.git("tag", "-a", "v9.9.8", "-m", "notes", env={"GIT_COMMITTER_NAME": f"Ada {TOKEN}"})
        self.assertRed(self.fx.gate("--range", f"{base}..v9.9.8"), ":(tagger) deny#2")
        self.fx.git("tag", "-a", "v9.9.7", "-m", "plain notes")
        self.assertGreen(self.fx.gate("--range", f"{base}..v9.9.7"), "1 tags")

    def test_staged_symlink_target(self):
        link = self.fx.repo / "link"
        link.symlink_to(f"/opt/{TOKEN}/data")
        self.fx.git("add", "link")
        self.assertRed(self.fx.gate("--staged"), "link:(symlink) deny#2")
        link.unlink()
        link.symlink_to("/opt/data")
        self.fx.git("add", "link")
        self.assertGreen(self.fx.gate("--staged"))

    def test_staged_binary_metadata_chunks(self):
        plain = png([(b"tEXt", b"Author\0" + f"by {TOKEN}".encode())])
        packed = png([(b"zTXt", b"Comment\0\0" + zlib.compress(f"shot of {TOKEN}".encode()))])
        utf16 = b"\x00\x01\x02" + f"owner {TOKEN}".encode("utf-16-le") + b"\x00\xff"
        # regime control: the compressed chunk must NOT carry the value as plain bytes,
        # or this case would re-test the printable-run path instead of the inflation path
        self.assertNotIn(TOKEN.encode(), packed)
        self.assertNotIn(TOKEN.encode(), utf16)
        for name, data in (("plain.png", plain), ("packed.png", packed), ("wide.bin", utf16)):
            with self.subTest(name=name):
                self.fx.write(name, data)
                self.fx.git("add", name)
                rc, out = self.fx.gate("--staged")
                self.assertRed((rc, out), f"{name}:@", "deny#2")
                self.fx.write(name, png([(b"tEXt", b"Author\0nobody")]) if name.endswith(".png")
                              else b"\x00\x01" + "owner nobody".encode("utf-16-le"))
                self.fx.git("add", name)
                self.assertGreen(self.fx.gate("--staged"))
                self.fx.git("rm", "-q", "--cached", name)

    def test_range_content_message_and_author(self):
        base = self.fx.git("rev-parse", "HEAD")
        self.fx.write("a.txt", f"{TOKEN}\n")
        self.fx.git("add", "a.txt")
        self.fx.git("commit", "-q", "-m", "add a")
        self.fx.git("commit", "-q", "--allow-empty", "-m", "subject", "-m", f"body names {TOKEN}")
        self.fx.git("commit", "-q", "--allow-empty", "-m", "by someone",
                    env={"GIT_AUTHOR_NAME": f"Ada {TOKEN}"})
        bad_head = self.fx.git("rev-parse", "HEAD")
        rc, out = self.fx.gate("--range", f"{base}..{bad_head}")
        self.assertRed((rc, out), ":a.txt:1 deny#2", ":(message):3 deny#2", ":(author) deny#2")
        self.assertIn("3 commits", out)
        # the whole-history forms reach the same commits; ..<b> is refused, never guessed
        self.assertRed(self.fx.gate("--range", bad_head), ":a.txt:1 deny#2")
        self.assertRed(self.fx.gate("--range", f"{'0' * 40}..{bad_head}"), ":a.txt:1 deny#2")
        self.assertEqual(self.fx.gate("--range", f"..{bad_head}")[0], 2)
        # the fix, scanned on its own, is green
        self.fx.write("a.txt", "fixed\n")
        self.fx.git("add", "a.txt")
        self.fx.git("commit", "-q", "-m", "fix a")
        self.assertGreen(self.fx.gate("--range", f"{bad_head}..HEAD"), "1 commits")

    def test_range_unresolvable_is_a_fault(self):
        self.assertFault(self.fx.gate("--range", "no-such-ref..HEAD"))

    def test_message(self):
        msg = self.fx.root / "MSG"
        msg.write_text(f"fix(x): subject\n\nthe body names {TOKEN}\n")
        self.assertRed(self.fx.gate("--message", str(msg)), "message:3 deny#2")
        msg.write_text("fix(x): subject\n\nthe body names nobody\n")
        self.assertGreen(self.fx.gate("--message", str(msg)))
        # below git's scissors line is the diff `commit -v` shows, never part of the message
        msg.write_text("fix(x): subject\n# ------------------------ >8 ------------------------\n"
                       f"+{TOKEN}\n")
        self.assertGreen(self.fx.gate("--message", str(msg)))

    def test_identity(self):
        self.assertRed(self.fx.gate("--identity", env={"GIT_AUTHOR_NAME": f"Ada {TOKEN}"}),
                       "identity:(author) deny#2")
        self.assertRed(self.fx.gate("--identity", env={"GIT_COMMITTER_EMAIL": f"{TOKEN}@example.com"}),
                       "identity:(committer) deny#2")
        self.assertGreen(self.fx.gate("--identity", env={"GIT_AUTHOR_NAME": "Ada Lovelace"}))

    def test_ref(self):
        self.assertRed(self.fx.gate("--ref", f"refs/heads/fix/{TOKEN}-thing"), "ref:refs/heads/fix/[deny#2]")
        self.assertGreen(self.fx.gate("--ref", "refs/heads/fix/thing"))

    def test_tree(self):
        tree = self.fx.root / "tree"
        (tree / "sub").mkdir(parents=True)
        (tree / "sub" / "f.md").write_text(f"# title\n{TOKEN}\n")
        (tree / "ok.md").write_text("fine\n")
        (tree / "l").symlink_to(f"../{TOKEN}")
        self.assertRed(self.fx.gate("--tree", str(tree)), "sub/f.md:2 deny#2", "l:(symlink) deny#2")
        (tree / "sub" / "f.md").write_text("# title\nnothing\n")
        (tree / "l").unlink()
        self.assertGreen(self.fx.gate("--tree", str(tree)))

    def test_tree_with_an_unreadable_directory_is_a_fault(self):
        # A directory the walk cannot list hides everything under it; "clean" would
        # be a verdict on files the gate never read.
        tree = self.fx.root / "tree"
        sealed = tree / "sealed"
        sealed.mkdir(parents=True)
        (sealed / "leak.txt").write_text(f"hello {TOKEN}\n")
        (tree / "ok.txt").write_text("fine\n")
        sealed.chmod(0)
        try:
            try:
                os.listdir(sealed)
            except PermissionError:
                pass
            else:
                self.skipTest("this user lists a mode-000 directory (root), so no directory is unreadable")
            self.assertFault(self.fx.gate("--tree", str(tree)), "sealed", "cannot be listed")
        finally:
            sealed.chmod(0o755)
        # control: the same tree, readable, shows what the fault was hiding
        self.assertRed(self.fx.gate("--tree", str(tree)), "sealed/leak.txt:1 deny#2")


class Allow(Base):
    def test_placeholder_passes_only_through_its_entry(self):
        line = f"owner = {PLACEHOLDER_ID}"
        self.fx.write("fixtures/a.json", f"{line}\n")
        self.fx.git("add", "-A")
        # the line trips a public pattern on its own, so a pass below is the entry's doing
        self.assertRed(self.fx.gate("--staged"), "fixtures/a.json:1 slack-id")
        rc, entry = self.fx.gate("--allow-entry", "fixtures/a.json:1")
        self.assertEqual(rc, 0, entry)
        (self.fx.repo / "tools/leak-gate/allow.txt").write_text(entry)
        self.assertGreen(self.fx.gate("--staged"), "1 allowed lines")
        # an allowed line that changes is no longer allowed
        self.fx.write("fixtures/a.json", f"{line} \n")
        self.fx.git("add", "-A")
        self.assertRed(self.fx.gate("--staged"), "fixtures/a.json:1 slack-id")

    def test_a_range_reads_allow_txt_from_its_tip_commit(self):
        # A scan from a checkout at an older commit (an upgrade's current tag, a
        # stale worktree) holds an older allow.txt in its working tree; the range's
        # own lines are allowed by the list the range's tip carries.
        base = self.fx.git("rev-parse", "HEAD")
        self.fx.write("fixtures/a.json", f"owner = {PLACEHOLDER_ID}\n")
        _, entry = self.fx.gate("--allow-entry", "fixtures/a.json:1")
        allow = self.fx.repo / "tools/leak-gate/allow.txt"
        allow.write_text("# fixture allow list\n" + entry)
        self.fx.git("add", "-A")
        self.fx.git("commit", "-q", "-m", "a placeholder and its entry")
        tip = self.fx.git("rev-parse", "HEAD")
        self.fx.git("checkout", "-q", "--detach", base)
        self.assertNotIn(entry.strip(), allow.read_text(), "control: the working tree holds the OLD list")
        self.assertGreen(self.fx.gate("--range", f"{base}..{tip}"), "1 allowed lines")
        self.fx.git("branch", "-q", "tip", tip)
        self.assertGreen(self.fx.gate("--history"), "1 allowed lines")
        # the tip decides, not the working tree: an entry only the working tree holds allows nothing
        self.fx.git("checkout", "-q", "tip")
        self.fx.write("fixtures/b.json", f"admin = {PLACEHOLDER_ID}\n")
        self.fx.git("add", "fixtures/b.json")
        self.fx.git("commit", "-q", "-m", "a second placeholder, its entry not committed")
        _, entry_b = self.fx.gate("--allow-entry", "fixtures/b.json:1")
        allow.write_text(allow.read_text() + entry_b)
        self.assertRed(self.fx.gate("--range", f"{tip}..HEAD"), "fixtures/b.json:1 slack-id")

    def test_allow_entry_never_silences_a_deny_hit(self):
        self.fx.write("b.txt", f"{PLACEHOLDER_ID} {TOKEN}\n")
        self.fx.git("add", "-A")
        _, entry = self.fx.gate("--allow-entry", "b.txt:1")
        (self.fx.repo / "tools/leak-gate/allow.txt").write_text(entry)
        rc, out = self.fx.gate("--staged")
        self.assertRed((rc, out), "b.txt:1 deny#2")
        self.assertNotIn("slack-id", out)


class DenyHalf(Base):
    def host(self, data: dict | None = None) -> Path:
        path = self.fx.root / "host.json"
        path.write_text(json.dumps(data or {"schema": 1, "agents_root": str(self.fx.root / "agents"),
                                            "fleet_checkout": str(self.fx.repo),
                                            "claims_dir": str(self.fx.root / "claims")}))
        return path

    def install(self, upstream, where: Path | None = None) -> Path:
        root = where or self.fx.root / "install"
        (root / ".claude").mkdir(parents=True, exist_ok=True)
        manifest = {"schema": 1, "fleet": {"repo": "x", "min_tag": "v1.0.0"},
                    "skills": ["chat-transport"], "transports": {"enabled": [], "default": None}}
        if upstream is not ...:
            manifest["upstream"] = upstream
        (root / ".claude" / "fleet.json").write_text(json.dumps(manifest))
        return root

    def staged_token(self):
        self.fx.write("t.txt", f"{TOKEN}\n")
        self.fx.git("add", "t.txt")

    def test_no_host_config_prints_the_skip_line(self):
        self.staged_token()
        rc, out = self.fx.gate("--staged", env={"FLEET_LEAK_DENY_FILE": None})
        self.assertEqual(rc, 0, out)
        self.assertIn("deny half not run: no fleet host config", out)

    def test_fleet_host_with_no_readable_deny_list_is_exit_3(self):
        self.staged_token()
        root = self.install({"deny_list": ".claude/fleet/missing-deny.txt"})
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": str(root)}
        self.assertFault(self.fx.gate("--staged", env=env), "the private deny list cannot be read")

    def test_fleet_host_reads_the_manifest_deny_list(self):
        self.staged_token()
        root = self.install({"deny_list": ".claude/fleet/leak-deny.txt"})
        (root / ".claude" / "fleet").mkdir()
        shutil.copy(self.fx.deny, root / ".claude" / "fleet" / "leak-deny.txt")
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": str(root)}
        self.assertRed(self.fx.gate("--staged", env=env), "t.txt:1 deny#2", "deny list: 4 entries")

    def test_deny_list_null_prints_the_skip_line(self):
        self.staged_token()
        root = self.install({"deny_list": None})
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": str(root)}
        rc, out = self.fx.gate("--staged", env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("sets upstream.deny_list to null", out)

    def test_manifest_without_deny_list_key_is_exit_3(self):
        root = self.install(...)
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": str(root)}
        self.assertFault(self.fx.gate("--staged", env=env), "has no upstream.deny_list")

    def test_no_resolvable_install_is_exit_3(self):
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": None, "CLAUDE_CONFIG_DIR": None}
        self.assertFault(self.fx.gate("--staged", env=env), "no install manifest resolves")

    def test_the_scanned_trees_own_manifest_is_never_read(self):
        # a manifest at the top of the repository being committed to, switching the deny half off
        self.install({"deny_list": None}, where=self.fx.repo)
        self.staged_token()
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": None, "CLAUDE_CONFIG_DIR": None}
        self.assertFault(self.fx.gate("--staged", env=env), "no install manifest resolves")

    def test_agent_home_project_resolves(self):
        agents = self.fx.root / "agents"
        project = self.install({"deny_list": str(self.fx.deny)}, where=agents / "ada" / "project")
        (agents / "ada" / ".claude").mkdir(parents=True)
        self.staged_token()
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(self.host()),
               "FLEET_CONTEXT_ROOT": None, "CLAUDE_CONFIG_DIR": str(agents / "ada" / ".claude")}
        self.assertRed(self.fx.gate("--staged", env=env), "t.txt:1 deny#2")
        self.install({"deny_list": None}, where=agents / "ada" / "second")
        self.assertFault(self.fx.gate("--staged", env=env), "2 install manifests")
        self.assertTrue(project.is_dir())

    def test_no_fleetlib_beside_the_gate_is_exit_3(self):
        # Python's own exit for an uncaught ImportError is 1, which every caller
        # reads as "findings"; the gate must say it has no verdict instead.
        self.assertGreen(self.fx.gate("--identity"))  # control: the same call with fleetlib
        shutil.rmtree(self.fx.repo / "lib")
        self.assertFault(self.fx.gate("--identity"), "fleetlib cannot be imported")

    def test_dangling_host_config_is_not_absence(self):
        link = self.fx.root / "host-link.json"
        link.symlink_to(self.fx.root / "nowhere.json")
        env = {"FLEET_LEAK_DENY_FILE": None, "FLEET_HOST_CONFIG": str(link)}
        self.assertFault(self.fx.gate("--staged", env=env), "the fleet host config cannot be read")

    def test_explicit_deny_file_missing_is_exit_3_even_off_a_fleet_host(self):
        self.assertFault(self.fx.gate("--staged", env={"FLEET_LEAK_DENY_FILE": str(self.fx.root / "nope")}),
                         "the private deny list cannot be read")

    def test_ci_never_reads_the_deny_list(self):
        self.staged_token()
        self.fx.git("commit", "-q", "-m", "bad")
        rc, out = self.fx.gate("--ci", "--range", "HEAD~1..HEAD")
        self.assertEqual(rc, 0, out)
        self.assertIn("deny half not run: --ci never reads the private deny list", out)
        rc, out = self.fx.gate("--ci", "--range", "HEAD~1..HEAD",
                               env={"FLEET_LEAK_DENY_FILE": str(self.fx.root / "missing")})
        self.assertEqual(rc, 0, out)


class AiIdentity(Base):
    def test_an_ai_tools_identity_is_refused_and_a_person_called_claude_is_not(self):
        at = "@"
        tool = {"GIT_AUTHOR_NAME": "Claude", "GIT_AUTHOR_EMAIL": "noreply" + at + "anthropic.com",
                "GIT_COMMITTER_NAME": "Claude", "GIT_COMMITTER_EMAIL": "noreply" + at + "anthropic.com"}
        rc, out = self.fx.gate("--identity", env=tool)
        self.assertRed((rc, out), "identity:(author) ai-identity", "identity:(committer) ai-identity")
        self.assertRed(self.fx.gate("--identity", env={"GIT_COMMITTER_NAME": "Claude Code",
                                                       "GIT_COMMITTER_EMAIL": "1+ada" + at + "users.noreply.github.com"}),
                       "identity:(committer) ai-identity")
        self.assertRed(self.fx.gate("--identity", env={"GIT_AUTHOR_EMAIL": "bot" + at + "mail.anthropic.com"}),
                       "identity:(author) ai-identity")
        # decoys: a person called Claude, and a look-alike domain, are not the tool
        person = {"GIT_AUTHOR_NAME": "Claude Shannon", "GIT_AUTHOR_EMAIL": "1+cshannon" + at + "users.noreply.github.com",
                  "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada" + at + "notanthropic.example.com"}
        self.assertGreen(self.fx.gate("--identity", env=person))
        # the same rule over a range, in the public half (CI's leak job runs --ci)
        base = self.fx.git("rev-parse", "HEAD")
        self.fx.git("commit", "-q", "--allow-empty", "-m", "by the tool", env=tool)
        self.fx.git("tag", "-a", "v9.9.9", "-m", "tagged by the tool", env=tool)
        rc, out = self.fx.gate("--ci", "--range", f"{base}..v9.9.9")
        self.assertRed((rc, out), ":(author) ai-identity", ":(committer) ai-identity", ":(tagger) ai-identity")
        bad = self.fx.git("rev-parse", "HEAD")
        self.fx.git("commit", "-q", "--allow-empty", "-m", "by a person", env=person)
        self.assertGreen(self.fx.gate("--ci", "--range", f"{bad}..HEAD"))


class DenyForms(Base):
    def lines(self, *texts: str):
        msg = self.fx.root / "M"
        msg.write_text("\n".join(texts) + "\n")
        return self.fx.gate("--message", str(msg))

    def test_word_is_a_case_insensitive_whole_word(self):
        self.assertRed(self.lines(TOKEN.upper()), "message:1 deny#2")
        self.assertRed(self.lines(f"{TOKEN}_bot"), "message:1 deny#2")
        self.assertRed(self.lines(f"bot_{TOKEN}"), "message:1 deny#2")
        self.assertGreen(self.lines(f"x{TOKEN}y", f"{TOKEN}2"))

    def test_case_is_case_sensitive(self):
        self.assertRed(self.lines(f"ask {CASE_TOKEN}."), "message:1 deny#3")
        self.assertGreen(self.lines(CASE_TOKEN.lower(), CASE_TOKEN.upper(), f"{CASE_TOKEN}ish"))

    def test_sub_matches_inside_words(self):
        self.assertRed(self.lines(f"x{SUB_TOKEN.upper()}y"), "message:1 deny#4")

    def test_re_entry(self):
        self.assertRed(self.lines(f"{RE_MARK}-42"), "message:1 deny#5")
        self.assertGreen(self.lines(f"{RE_MARK}-x"))

    def test_normalized_variants_match_and_are_masked(self):
        fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in TOKEN)
        split = TOKEN[:3] + "\u200b" + TOKEN[3:]
        rc, out = self.lines(fullwidth, split)
        self.assertRed((rc, out), "message:1 deny#2", "message:2 deny#2")

    def test_invalid_entries_are_refused_by_line_without_their_text(self):
        marker = "secret" + "entrytext"
        for bad in (f"name:{marker}", f"re:{marker}(", f"re:({marker})?", "word:   "):
            with self.subTest(entry=bad.split(":")[0]):
                self.fx.deny.write_text(f"# c\nword:{TOKEN}\n{bad}\n")
                rc, out = self.fx.gate("--identity")
                self.assertFault((rc, out), "deny#3")
                self.assertNotIn(marker, out)

    def test_empty_deny_list_is_a_fault(self):
        self.fx.deny.write_text("# only comments\n\n")
        self.assertFault(self.fx.gate("--identity"), "has no entries")


class PublicPatterns(Base):
    def test_each_class_and_the_email_exclusions(self):
        at = "@"
        cases = {
            "slack-id": "user " + "W0" + "ABCDEFGH" + " joined",
            "slack-token": "token " + "xo" + "xb-" + "123",
            "home-path": "cd " + "/ho" + "me/ada/projects",
            "email": "mail ada.l" + at + "corp" + ".io today",
            "tailscale-name": "box.tail1234" + ".ts" + ".net",
            "gcp-service-account": "bot" + at + "proj.iam" + ".gserviceaccount.com",
            "figma-url": "https://www.fig" + "ma.com/design/" + "AbCdEfGhIjKlMn",
            "google-doc-url": "https://docs.goo" + "gle.com/document/d/" + "a" * 25,
            "notion-url": "https://www.not" + "ion.so/Page-" + "0123456789abcdef" * 2,
        }
        mac_home = "/Us" + "ers/Ada Lovelace/x"
        # the exclusions are exact: a look-alike local part or domain is still an address
        cases_extra = ["noreply" + at + "github.company.io", "mynoreply" + at + "github.com", "gitx" + at + "github.com"]
        clean = [
            "a" + at + "example.com, b" + at + "sub.example.org and c" + at + "example.net.",
            "3628395+someone" + at + "users.noreply.github.com",
            "noreply" + at + "anthropic.com",
            "git" + at + "github.com:owner/agent-fleet.git",
            "GitHub <noreply" + at + "github.com>",
            "U0" + "short",
        ]
        tree = self.fx.root / "pp"
        tree.mkdir()
        lines = list(cases.values()) + [mac_home] + clean
        (tree / "f.txt").write_text("\n".join(lines) + "\n")
        rc, out = self.fx.gate("--tree", str(tree))
        self.assertEqual(rc, 1, out)
        for n, cls in enumerate(list(cases) + ["home-path"], 1):
            self.assertIn(f"f.txt:{n} {cls}", out)
        for n in range(len(cases) + 2, len(lines) + 1):
            self.assertNotIn(f"f.txt:{n} ", out, f"line {n} ({lines[n - 1]!r}) must be clean")
        self.assertIn("f.txt:4 email", out)
        (tree / "g.txt").write_text("\n".join(cases_extra) + "\n")
        rc, out = self.fx.gate("--tree", str(tree))
        for n in range(1, len(cases_extra) + 1):
            self.assertIn(f"g.txt:{n} email", out)


class Gitleaks(Base):
    def finding(self, path: str, line: int = 1, commit: str = "") -> str:
        return json.dumps([{"RuleID": "fake-rule", "File": path, "StartLine": line, "Commit": commit,
                            "Secret": "SHOULD-NEVER-PRINT", "Match": "SHOULD-NEVER-PRINT"}])

    def test_a_finding_is_reported_without_the_secret(self):
        tree = self.fx.root / "t"
        tree.mkdir()
        (tree / "c.txt").write_text("x\n")
        rc, out = self.fx.gate("--tree", str(tree), env={"FAKE_GITLEAKS_FINDINGS": self.finding(str(tree / "c.txt"))})
        self.assertRed((rc, out), "c.txt:1 gitleaks:fake-rule")
        self.assertNotIn("SHOULD-NEVER-PRINT", out)

    def test_the_gate_passes_the_no_bypass_flags(self):
        # The statement of the rule, on the argv: the real-gitleaks cases below show
        # each blinding mechanism failing, but only for the mechanisms they plant.
        log = self.fx.root / "argv.log"
        tree = self.fx.root / "t"
        tree.mkdir()
        self.fx.write("s.txt", "x\n")
        self.fx.git("add", "s.txt")
        self.fx.gate("--tree", str(tree), "--staged", env={"FAKE_GITLEAKS_LOG": str(log)})
        scans = [json.loads(line) for line in log.read_text().splitlines() if '"version"' not in line]
        self.assertEqual(len(scans), 2, scans)
        # Resolved, as leak_gate.py resolves its own directory: wherever TMPDIR sits behind
        # a symlink (macOS's /var/folders is /private/var/folders) the two spellings differ.
        own_config = os.path.realpath(self.fx.repo / "tools" / "leak-gate" / "gitleaks.toml")
        for argv in scans:
            for flag in ("--ignore-gitleaks-allow", "--gitleaks-ignore-path", "--redact"):
                self.assertIn(flag, argv)
            # gitleaks reads the gate's own configuration, never one from the tree under scan,
            # and never renders a change through git (whose attributes and config the writer controls)
            self.assertEqual(argv[argv.index("--config") + 1], own_config, argv)
            self.assertEqual(argv[0], "dir", argv)

    def blind_gitleaks(self, fx: Fixture, exe: str, *args: str) -> int:
        """gitleaks run directly, the way a tool that trusts the tree runs it: the
        regime control that the planted mechanism really does blind gitleaks."""
        return fx.run([exe, *args, "--no-banner", "--log-level", "error", "--exit-code", "9"]).returncode

    def test_repository_attributes_cannot_blind_gitleaks(self):
        exe = real_gitleaks()
        line = f'token = "{github_pat()}"\n'
        for label, place, text in ((".gitattributes -diff", ".gitattributes", "*.txt -diff\n"),
                                   (".gitattributes binary", ".gitattributes", "*.txt binary\n"),
                                   ("info/attributes -diff", ".git/info/attributes", "*.txt -diff\n")):
            with self.subTest(label):
                fx = self.fresh()
                env = {"FLEET_GITLEAKS": exe}
                fx.write(place, text)
                fx.write("conf.txt", line)
                fx.git("add", "-A")
                self.assertEqual(self.blind_gitleaks(fx, exe, "git", "--pre-commit", "--staged", "."), 0,
                                 "regime: the attribute does not blind gitleaks' own git diff")
                self.assertRed(fx.gate("--staged", env=env), "conf.txt:1 gitleaks:github-pat")
                fx.git("commit", "-q", "-m", "conf")
                self.assertEqual(self.blind_gitleaks(fx, exe, "git", "--log-opts=HEAD~1..HEAD", "."), 0,
                                 "regime: the attribute does not blind gitleaks' own git log")
                self.assertRed(fx.gate("--range", "HEAD~1..HEAD", env=env), ":conf.txt:1 gitleaks:github-pat")

    def test_a_gitleaks_toml_in_the_scanned_tree_is_never_read(self):
        exe = real_gitleaks()
        env = {"FLEET_GITLEAKS": exe}
        line = f'token = "{github_pat()}"\n'
        permissive = "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''.*''']\n"
        self.fx.write("conf.txt", line)
        self.fx.git("add", "conf.txt")
        self.fx.write(".gitleaks.toml", permissive)  # untracked: gitleaks reads the work tree
        self.assertEqual(self.blind_gitleaks(self.fx, exe, "git", "--pre-commit", "--staged", "."), 0,
                         "regime: the work tree's .gitleaks.toml does not blind gitleaks")
        self.assertRed(self.fx.gate("--staged", env=env), "conf.txt:1 gitleaks:github-pat")
        self.fx.git("add", ".gitleaks.toml")
        self.fx.git("commit", "-q", "-m", "conf")
        self.assertRed(self.fx.gate("--range", "HEAD~1..HEAD", env=env), ":conf.txt:1 gitleaks:github-pat")
        tree = self.fx.root / "t"
        tree.mkdir()
        (tree / "conf.txt").write_text(line)
        (tree / ".gitleaks.toml").write_text(permissive)
        self.assertEqual(self.blind_gitleaks(self.fx, exe, "dir", str(tree)), 0,
                         "regime: a .gitleaks.toml at a directory's top does not blind gitleaks dir")
        self.assertRed(self.fx.gate("--tree", str(tree), env=env), "conf.txt:1 gitleaks:github-pat")

    def test_colour_config_cannot_blind_gitleaks(self):
        exe = real_gitleaks()
        line = f'token = "{github_pat()}"\n'
        for key in ("color.ui", "color.diff"):
            with self.subTest(key):
                fx = self.fresh()
                env = {"FLEET_GITLEAKS": exe}
                fx.git("config", key, "always")
                fx.write("conf.txt", line)
                fx.git("add", "conf.txt")
                self.assertEqual(self.blind_gitleaks(fx, exe, "git", "--pre-commit", "--staged", "."), 0,
                                 f"regime: {key}=always does not blind gitleaks' own git diff")
                self.assertRed(fx.gate("--staged", env=env), "conf.txt:1 gitleaks:github-pat")
                fx.git("commit", "-q", "-m", "conf")
                self.assertRed(fx.gate("--range", "HEAD~1..HEAD", env=env), ":conf.txt:1 gitleaks:github-pat")

    def test_wrong_version_missing_and_crash_are_faults(self):
        tree = self.fx.root / "t"
        tree.mkdir()
        self.assertFault(self.fx.gate("--tree", str(tree), env={"FAKE_GITLEAKS_VERSION": "8.0.0"}),
                         "pins v" + PINNED, "install-gitleaks.sh")
        self.assertFault(self.fx.gate("--tree", str(tree), env={"FAKE_GITLEAKS_CRASH": "1"}),
                         "gitleaks dir failed (exit 1)")
        no_gitleaks = {"FLEET_GITLEAKS": None, "PATH": "/usr/bin:/bin"}
        if shutil.which("gitleaks", path="/usr/bin:/bin"):
            self.skipTest("a system gitleaks on /usr/bin:/bin hides the missing case")
        self.assertFault(self.fx.gate("--tree", str(tree), env=no_gitleaks), "is not installed")
        # scopes that need no gitleaks do not ask for it
        self.assertGreen(self.fx.gate("--identity", env=no_gitleaks))

    def test_real_gitleaks_finds_a_secret_in_every_git_and_file_scope(self):
        exe = real_gitleaks()
        env = {"FLEET_GITLEAKS": exe}
        secret = github_pat()
        content = f'config\ntoken = "{secret}"\n'
        tree = self.fx.root / "t"
        tree.mkdir()
        (tree / "conf.txt").write_text(content)
        results = {"--tree": self.fx.gate("--tree", str(tree), env=env)}
        self.fx.write("conf.txt", content)
        self.fx.git("add", "conf.txt")
        results["--staged"] = self.fx.gate("--staged", env=env)
        self.fx.git("commit", "-q", "-m", "conf")
        results["--range"] = self.fx.gate("--range", "HEAD~1..HEAD", env=env)
        msg = self.fx.root / "MSG"
        msg.write_text(f"subject\n\n{secret}\n")
        results["--message"] = self.fx.gate("--message", str(msg), env=env)
        for scope, (rc, out) in results.items():
            with self.subTest(scope=scope):
                self.assertEqual(rc, 1, out)
                self.assertIn("gitleaks:github-pat", out)
                self.assertNotIn(secret, out)
        self.assertIn("conf.txt:2 gitleaks:github-pat", results["--tree"][1])
        self.assertIn("conf.txt:2 gitleaks:github-pat", results["--staged"][1])
        # fixed: green
        (tree / "conf.txt").write_text("config\ntoken = from-the-environment\n")
        self.assertGreen(self.fx.gate("--tree", str(tree), env=env))
        # and allow.txt silences a real finding by the exact line, as it does a public pattern
        (tree / "conf.txt").write_text(content)
        _, entry = self.fx.gate("--allow-entry", str(tree / "conf.txt") + ":2")
        digest = entry.strip().rsplit(":", 1)[1]
        (self.fx.repo / "tools/leak-gate/allow.txt").write_text(f"conf.txt:{digest}\n")
        self.assertGreen(self.fx.gate("--tree", str(tree), env=env), "1 allowed lines")


class Hooks(Base):
    hooks = True

    def commit(self, *args, cwd=None):
        return self.fx.run(["git", "commit", "-q", *args], cwd=cwd)

    def test_pre_commit_refuses_a_staged_value_and_accepts_the_fix(self):
        head = self.fx.git("rev-parse", "HEAD")
        self.fx.write("doc.md", f"{TOKEN}\n")
        self.fx.git("add", "doc.md")
        proc = self.commit("-m", "docs(x): add")
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("doc.md:1 deny#2", proc.stdout + proc.stderr)
        self.assertMasked(proc.stdout + proc.stderr)
        self.assertEqual(self.fx.git("rev-parse", "HEAD"), head)
        self.fx.write("doc.md", "fine\n")
        self.fx.git("add", "doc.md")
        proc = self.commit("-m", "docs(x): add")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_hooks_run_from_a_subdirectory_and_from_a_linked_worktree(self):
        (self.fx.repo / "sub").mkdir()
        self.fx.write("sub/x.md", f"{TOKEN}\n")
        self.fx.git("add", "sub/x.md")
        proc = self.commit("-m", "x", cwd=self.fx.repo / "sub")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("sub/x.md:1 deny#2", proc.stdout + proc.stderr)
        self.fx.git("reset", "-q")
        wt = self.fx.root / "wt"
        self.fx.git("worktree", "add", "-q", str(wt), "-b", "test/wt")
        (wt / "y.md").write_text(f"{TOKEN}\n")
        self.fx.git("add", "y.md", cwd=wt)
        proc = self.commit("-m", "y", cwd=wt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("y.md:1 deny#2", proc.stdout + proc.stderr)

    def test_a_fenced_commit_is_judged_on_exactly_what_it_commits(self):
        self.fx.write("bad.md", f"{TOKEN}\n")
        self.fx.write("good.md", "fine\n")
        self.fx.git("add", "bad.md", "good.md")
        # `git commit -- good.md` records good.md only (a temporary index): the hook must judge that
        proc = self.commit("-m", "docs(x): good", "--", "good.md")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.fx.git("show", "--name-only", "--format=", "HEAD"), "good.md")
        proc = self.commit("-m", "docs(x): bad", "--", "bad.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("bad.md:1 deny#2", proc.stdout + proc.stderr)

    def push_setup(self):
        remote = self.fx.root / "remote.git"
        self.fx.run(["git", "init", "-q", "--bare", str(remote)], cwd=self.fx.root)
        self.fx.git("remote", "add", "origin", str(remote))
        proc = self.fx.run(["git", "push", "-q", "origin", "main"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_pre_push_refuses_a_no_verify_commit(self):
        self.push_setup()
        self.fx.write("n.md", f"{TOKEN}\n")
        self.fx.git("add", "n.md")
        self.assertEqual(self.commit("--no-verify", "-m", "docs(x): sneak").returncode, 0)
        proc = self.fx.run(["git", "push", "origin", "main"])
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("n.md:1 deny#2", proc.stderr + proc.stdout)
        self.assertMasked(proc.stdout + proc.stderr)
        self.fx.write("n.md", "fixed\n")
        self.fx.git("add", "n.md")
        self.commit("-m", "docs(x): fix")
        # the bad commit is still in the range, so the push stays refused: history keeps it
        self.assertNotEqual(self.fx.run(["git", "push", "origin", "main"]).returncode, 0)

    def test_pre_push_checks_every_ref_of_one_push(self):
        self.push_setup()
        self.fx.git("checkout", "-q", "-b", "fix/clean")
        self.fx.write("c.md", "clean\n")
        self.fx.git("add", "c.md")
        self.commit("-m", "docs(x): clean")
        self.fx.git("checkout", "-q", "-b", "fix/dirty", "main")
        self.fx.write("d.md", f"{TOKEN}\n")
        self.fx.git("add", "d.md")
        self.commit("--no-verify", "-m", "docs(x): dirty")
        for order in (["fix/clean", "fix/dirty"], ["fix/dirty", "fix/clean"]):
            with self.subTest(order=order):
                proc = self.fx.run(["git", "push", "origin", *order])
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("d.md:1 deny#2", proc.stdout + proc.stderr)
        proc = self.fx.run(["git", "push", "origin", "fix/clean"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_pre_push_refuses_a_bad_ref_name(self):
        self.push_setup()
        proc = self.fx.run(["git", "push", "origin", f"main:refs/heads/fix/{TOKEN}"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ref:refs/heads/fix/[deny#2] deny#2", proc.stdout + proc.stderr)
        self.assertMasked(proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
