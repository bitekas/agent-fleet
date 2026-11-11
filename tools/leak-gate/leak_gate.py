#!/usr/bin/env python3
"""leak_gate.py - the commit gate's leak check.

Catches ACCIDENTAL publication by an authorized writer: an id quoted from a
session's context, a path captured into a fixture, a private name in a commit
message, a branch or an author. A writer who means to publish something can
always do so; that is out of scope.

Usage: python3 tools/leak-gate/leak_gate.py <scope>... [--ci]

Scopes (any number in one run):
  --staged            the staged change (what `git commit` will record, so the
                      temporary index of `git commit -- <paths>` included):
                      every added, changed, renamed or copied path's name, its
                      blob, and every symlink target. gitleaks over those blobs.
  --range <a>..<b>    every commit in the range: changed paths, blobs, symlink
                      targets, the message, the author and committer, and an
                      annotated tag at <b>. A bare <b>, or an all-zero <a> (the
                      old value git reports for a ref that a push creates),
                      means the whole history of <b>. gitleaks over those blobs.
  --history           every commit reachable from any ref, every ref name, and
                      every annotated tag. gitleaks over every commit's blobs.
  --tree <dir>        every entry under <dir>, which need not be a git tree:
                      names, contents, symlink targets (never followed). A
                      directory that cannot be listed is exit 3.
  --message <file>    a commit-message file (the commit-msg hook).
  --identity          the author and committer git is about to record.
  --ref <name>        a ref name that is being published.
  --ci                never read the private deny list (CI has none).
  --allow-entry <path>:<line>
                      print the allow.txt entry for that line of a working-tree
                      file, and scan nothing.

Three sources:
  1. patterns.txt beside this file: the public patterns, `<class><TAB><regex>`.
  2. the private deny list: $FLEET_LEAK_DENY_FILE, else the install manifest's
     upstream.deny_list (see "When the deny half runs").
  3. gitleaks, at the version gitleaks.version pins: $FLEET_GITLEAKS, else
     `gitleaks` on PATH, else ~/.local/bin/gitleaks; configured by
     gitleaks.toml beside this file.
And one rule for identities (author, committer, tagger): an AI tool's own
identity - an address at anthropic.com, or the bare name Claude or Claude Code -
is the finding `ai-identity`. A commit is authored by the person or agent who
made it, never by a tool; a person called Claude has a surname and an address
of their own, and passes.

Output: one line per finding, `<where> <class>`. <class> is a public pattern's
class, `ai-identity`, `gitleaks:<rule>`, or `deny#<n>`, where n is the entry's
LINE NUMBER in the deny list. Then one summary line saying what was scanned.

Exit codes: 0 clean; 1 one or more findings; 2 usage error; 3 instrument fault
(an unreadable or invalid rule file, a deny list required and not readable,
gitleaks missing or at the wrong version, an unresolvable range, a directory
--tree cannot list). A 3 prints "no verdict": the subject was not judged, so
nothing about it was found.

When the deny half runs (fail closed):
  * --ci: never. One line says so.
  * $FLEET_LEAK_DENY_FILE set: that file is required. Unreadable: exit 3.
  * no fleet host config ($FLEET_HOST_CONFIG, else
    ~/.config/agent-fleet/host.json): an outside contributor's clone. One line
    says the deny half did not run; public patterns and gitleaks still do.
  * a fleet host: the install manifest is required, resolved from
    $FLEET_CONTEXT_ROOT, else the calling agent's home project (the one
    `<agent home>/*/.claude/fleet.json` beside $CLAUDE_CONFIG_DIR). Its
    upstream.deny_list names the list, relative to the install root; a list
    that cannot be read is exit 3. upstream.deny_list = null is the install's
    explicit statement that it has no private values: one line says so.

LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole:

  * A DENY HIT NEVER PRINTS THE MATCHED TEXT. Every line this script prints,
    every location and every fault message included, passes through the deny
    masker, which replaces each deny match with `[deny#<n>]`. A finding's
    location can itself be the leak (a file NAME, a branch name, a symlink
    target), so masking only the "value" column would print the value in the
    path column. Remove the masker and the gate's own output repeats, into a
    terminal or a CI log, exactly what it refused.

  * THE INSTALL MANIFEST IS NEVER READ FROM THE TREE UNDER SCAN. The leak gate
    resolves the manifest with fleetlib's install_root(git_top=False):
    $FLEET_CONTEXT_ROOT or the agent's home project, never the git top level of
    the working directory (fleetlib's step 2), because in a hook that top level
    IS the repository being committed to. A commit that added a
    `.claude/fleet.json` with upstream.deny_list = null at this repository's
    root would otherwise switch the deny half off for every later commit, with
    nothing but a polite skip line to show for it. Drop git_top=False and
    test_the_scanned_trees_own_manifest_is_never_read goes red.

  * A MISSING HOST CONFIG MEANS ABSENT, AND NOTHING ELSE DOES. Only
    "no such file" (ENOENT, ENOTDIR) reads as "not a fleet host". A host
    config that exists but cannot be read - a dangling symlink, a permission
    error, bad JSON - is exit 3. A check that treated every lstat error as
    absence would skip the deny half on the one host it exists for.

  * AN EMPTY DENY LIST IS A FAULT, NOT A PASS. A truncated or wrongly
    resolved file with zero entries would otherwise pass every commit while
    looking configured. An install with no private values says so with
    upstream.deny_list = null, which prints its skip line.

  * NORMALIZE BEFORE MATCHING. Text is NFKC-normalized and stripped of
    zero-width and other invisible characters first, so a fullwidth or
    zero-width-split copy of a value matches like the plain one.

  * BINARY BLOBS ARE SCANNED, NOT SKIPPED. A blob with a NUL byte, or that is
    not valid UTF-8, is scanned as its printable runs of six or more
    characters (UTF-8 and UTF-16LE), plus the inflated text of compressed PNG
    text chunks (zTXt, iTXt), because image metadata is where a captured
    screenshot carries a name or a path.

  * DELETED PATHS, AND THE SOURCE SIDE OF A RENAME, ARE NOT SCANNED. They are
    already in history, where --range and --history find them; refusing the
    commit that removes a leaking file would block the fix.

  * ALLOW.TXT SILENCES PUBLIC-PATTERN AND GITLEAKS HITS ONLY, BY EXACT LINE.
    An entry is `<path>:<sha256 of the exact line>`, so an allowed line that
    changes is no longer allowed. It never silences a deny hit: the file is
    public, and a hash of a short private line is a dictionary lookup away from
    the value. There is no inline ignore marker, and gitleaks runs with
    --ignore-gitleaks-allow and an empty .gitleaksignore path, because an
    inline marker is a bypass any writer can type.

  * A RANGE IS JUDGED BY THE ALLOW.TXT ITS TIP COMMIT CARRIES, never by the
    working tree's. --range reads `<b>:tools/leak-gate/allow.txt`, --history
    the union of that file at every ref and HEAD; --staged and --tree read the
    working tree's. A checkout at an older commit (the host checkout judging
    an upgrade's range, a stale worktree) holds an older list, and judged by
    it every placeholder line allowed since is a false finding; a working-tree
    entry nobody committed would pass a push that CI, which checks out the
    tip, refuses. The range supplying its own list widens nothing: an entry is
    a line of the range's diff like any other, and it never silences a deny
    hit.

  * GITLEAKS JUDGES THE BLOBS THIS SCRIPT ENUMERATED, NEVER GIT'S RENDERING OF
    THEM. Every git scope writes each distinct (path, blob) it scanned to a
    temporary tree, `<slot>/<path>` (a mkdtemp directory, mode 0700, removed
    when the run ends), and runs `gitleaks dir` over that. Run as
    `gitleaks git`, gitleaks builds its own `git diff` / `git log -p`, and git
    renders a change through state the writer controls: a `-diff` or `binary`
    attribute (in the tree, in $GIT_DIR/info/attributes, in a global
    attributes file) turns the file into "Binary files differ", and
    color.ui=always puts escape codes into the patch. Each one makes gitleaks
    find nothing and the gate print "clean" (measured with gitleaks 8.30.1 and
    git 2.53). Environment overrides close the tree attributes and the colour
    keys only; info/attributes has no switch at all. The written tree has no
    attributes and no config, so there is nothing to blind. gitleaks reads
    whole blobs, as the deny and public halves do: a secret is reported for
    every commit of the range whose changed blob holds it, not only the commit
    that added it.

  * GITLEAKS RUNS WITH --config gitleaks.toml FROM BESIDE THIS SCRIPT. Without
    it gitleaks loads a .gitleaks.toml from the top of the directory it scans,
    so an untracked file in a clone, a committed one, or one at the top of a
    --tree directory could allowlist everything and the gate would print
    "clean". gitleaks.toml extends the default rules and changes nothing else;
    a missing gitleaks.toml is exit 3.

  * `..<b>` IS REFUSED. git reads it as HEAD..<b>, so a caller that meant "the
    whole history of b" would silently scan the wrong range - often nothing.
    The whole history is a bare `<b>`, git's own meaning, or `000..<b>`.

  * GITLEAKS IS CHECKED, NOT ASSUMED. Missing, or at a version other than the
    pinned one, is exit 3 naming the install command; its exit code is set to
    9 so that "found secrets" (9) cannot be confused with "crashed" (1).
    Nothing it prints reaches this script's output: findings come from its
    JSON report, without the secret, with --redact as a second net.

  * EVERY SUBPROCESS GETS stdin FROM /dev/null (except gitleaks reading a
    message on stdin). The pre-push hook feeds its ref list on stdin; a child
    that read it would end the hook's loop early and leave the remaining refs
    unchecked.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zlib
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
PATTERNS_FILE = HERE / "patterns.txt"
ALLOW_FILE = HERE / "allow.txt"
ALLOW_PATH = "tools/leak-gate/allow.txt"  # the same file, as a path inside a commit
VERSION_FILE = HERE / "gitleaks.version"
GITLEAKS_CONFIG = HERE / "gitleaks.toml"
INSTALL_HINT = "bash tools/leak-gate/install-gitleaks.sh ~/.local/bin"
LIB = HERE.parents[1] / "lib"

OK, FINDING, USAGE, FAULT = 0, 1, 2, 3

# fleetlib comes from THIS repository's lib/, by path: an outside contributor's
# clone has no fleet install to import it from, and the hooks run there too.
# No bytecode is written, so a hook leaves no __pycache__ in the tree under
# commit. A failed import is exit 3 (no verdict), never the exit 1 of an uncaught
# ImportError, which every caller reads as "findings".
sys.dont_write_bytecode = True
sys.path.insert(0, str(LIB))
try:
    from fleetlib import FleetError, paths as fleet_paths
except ImportError as _exc:
    print(f"leak-gate: FAULT: fleetlib cannot be imported from {LIB}: {_exc}", file=sys.stderr)
    print("leak-gate: no verdict - the subject was not judged", file=sys.stderr)
    sys.exit(FAULT)

GITLEAKS_LEAK_EXIT = 9
INFLATE_LIMIT = 8 * 1024 * 1024

INVISIBLE = dict.fromkeys(map(ord, (
    "\u00ad\u034f\u180e\u200b\u200c\u200d\u200e\u200f"
    "\u2060\u2061\u2062\u2063\u2064\ufeff")))
SCISSORS = re.compile(r"^. -{24} >8 -{24}\s*$")
PRINTABLE_RUN = re.compile(
    rb"(?:[\t\x20-\x7e]|[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}"
    rb"|[\xf0-\xf4][\x80-\xbf]{3}){6,}")
UTF16_RUN = re.compile(rb"(?:[\t\x20-\x7e]\x00){6,}")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ALNUM_BEFORE = r"(?<![^\W_])"
ALNUM_AFTER = r"(?![^\W_])"
AI_NAME = re.compile(r"(?i)claude(?: code)?")
AI_DOMAIN = re.compile(r"(?i)@(?:[a-z0-9-]+\.)*anthropic\.com\Z")


class Fault(Exception):
    """An instrument fault: exit 3, no verdict on the subject."""


class Usage(Exception):
    """A usage error: exit 2."""


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text.translate(INVISIBLE)).translate(INVISIBLE)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ai_identity(ident: str) -> bool:
    """`Name <address>` is an AI tool's own identity (see the header)."""
    name, _, rest = normalize(ident).partition("<")
    address = rest.strip().removesuffix(">").strip()
    return bool(AI_NAME.fullmatch(name.strip())) or bool(AI_DOMAIN.search(address))


# ---------------------------------------------------------------- rule files

def _read(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise Fault(f"{what} cannot be read ({path}): {type(exc).__name__}") from None


def _rule_lines(text: str):
    for lineno, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if line.strip() and not line.lstrip().startswith("#"):
            yield lineno, line


def load_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for lineno, line in _rule_lines(_read(PATTERNS_FILE, "the public pattern file")):
        cls, tab, rx = line.partition("\t")
        if not tab or not cls.strip() or not rx:
            raise Fault(f"{PATTERNS_FILE.name}:{lineno}: want <class><TAB><regex>")
        try:
            compiled = re.compile(rx)
        except re.error as exc:
            raise Fault(f"{PATTERNS_FILE.name}:{lineno}: {exc}") from None
        if compiled.search("") is not None:
            raise Fault(f"{PATTERNS_FILE.name}:{lineno}: matches the empty string")
        patterns.append((cls.strip(), compiled))
    if not patterns:
        raise Fault(f"{PATTERNS_FILE.name} holds no pattern, so the public half would check nothing")
    return patterns


def parse_allow(text: str, name: str) -> set[tuple[str, str]]:
    allowed = set()
    for lineno, line in _rule_lines(text):
        path, sep, digest = line.rpartition(":")
        if not sep or not path or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Fault(f"{name}:{lineno}: want <path>:<sha256 of the line>")
        allowed.add((path, digest))
    return allowed


def load_allow() -> set[tuple[str, str]]:
    """The working tree's allow list: --staged and --tree."""
    return parse_allow(_read(ALLOW_FILE, "the allow list"), ALLOW_FILE.name)


def allow_at(objs: "Objects", rev: str) -> set[tuple[str, str]]:
    """The allow list `rev` carries (none when it has no allow.txt): --range, --history."""
    got = objs.read(f"{rev}:{ALLOW_PATH}", optional=True)
    if got is None or got[0] != "blob":
        return set()
    try:
        text = got[1].decode("utf-8")
    except UnicodeDecodeError:
        raise Fault(f"{ALLOW_PATH} at {rev[:12]} is not UTF-8") from None
    return parse_allow(text, f"{ALLOW_PATH} at {rev[:12]}")


def _bounded(text: str, flags: int) -> re.Pattern:
    before = ALNUM_BEFORE if text[0].isalnum() else ""
    after = ALNUM_AFTER if text[-1].isalnum() else ""
    return re.compile(before + re.escape(text) + after, flags)


class DenyList:
    """The private deny list. Its entries are never printed, only `deny#<line>`."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: list[tuple[int, re.Pattern]] = []
        for lineno, line in _rule_lines(_read(path, "the private deny list")):
            self.entries.append((lineno, self._compile(lineno, line.lstrip())))
        if not self.entries:
            raise Fault(f"the private deny list has no entries ({path}); an install "
                        "with no private values sets upstream.deny_list to null")

    @staticmethod
    def _compile(n: int, line: str) -> re.Pattern:
        form, sep, text = line.partition(":")
        if not sep or form not in ("sub", "word", "case", "re"):
            raise Fault(f"deny#{n}: unknown entry form; an entry starts with sub:, word:, case: or re:")
        if form == "re":
            try:
                compiled = re.compile(text)
            except re.error:
                raise Fault(f"deny#{n}: the re: entry does not compile") from None
            if compiled.search("") is not None:
                raise Fault(f"deny#{n}: the re: entry matches the empty string, so it matches every line")
            return compiled
        text = normalize(text.strip())
        if not text:
            raise Fault(f"deny#{n}: empty {form}: entry")
        if form == "sub":
            return re.compile(re.escape(text), re.IGNORECASE)
        return _bounded(text, re.IGNORECASE if form == "word" else 0)

    def hits(self, norm: str) -> list[int]:
        return [n for n, rx in self.entries if rx.search(norm)]

    def mask(self, norm: str) -> str:
        spans = sorted((m.start(), m.end(), n) for n, rx in self.entries
                       for m in rx.finditer(norm) if m.end() > m.start())
        merged: list[list[int]] = []
        for start, end, n in spans:
            if merged and start < merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end, n])
        out, pos = [], 0
        for start, end, n in merged:
            out.append(norm[pos:start])
            out.append(f"[deny#{n}]")
            pos = end
        out.append(norm[pos:])
        return "".join(out)


# ---------------------------------------------------------- deny resolution

def _read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Fault(f"{what} cannot be read ({path}): {type(exc).__name__}") from None


def _host_config_present(path: Path) -> bool:
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise Fault(f"the fleet host config cannot be checked ({path}): {type(exc).__name__}") from None
    return True


def install_root() -> Path:
    """The install whose manifest names the deny list: fleetlib's resolver
    WITHOUT its git-top-level step, so never the scanned tree."""
    try:
        return fleet_paths.install_root(git_top=False)
    except FleetError as exc:
        raise Fault(f"this is a fleet host and {exc}; or set FLEET_LEAK_DENY_FILE to its "
                    "deny list") from None


def resolve_deny(ci: bool, out: "Out") -> DenyList | None:
    if ci:
        out.note("deny half not run: --ci never reads the private deny list")
        return None
    explicit = os.environ.get("FLEET_LEAK_DENY_FILE")
    if explicit:
        return DenyList(Path(explicit).expanduser())
    host_path = fleet_paths.host_config_path()
    if not _host_config_present(host_path):
        out.note(f"deny half not run: no fleet host config at {host_path} (not a fleet host); "
                 "public patterns and gitleaks only")
        return None
    _read_json(host_path, "the fleet host config")  # present: unreadable or not JSON is exit 3
    root = install_root()
    manifest = _read_json(root / fleet_paths.MANIFEST, "the install manifest")
    upstream = manifest.get("upstream") if isinstance(manifest, dict) else None
    if not isinstance(upstream, dict) or "deny_list" not in upstream:
        raise Fault(f"this is a fleet host and the install manifest at {root} has no "
                    "upstream.deny_list; name the list, or set it to null to state the "
                    "install has no private values")
    value = upstream["deny_list"]
    if value is None:
        out.note(f"deny half not run: the install manifest at {root} sets upstream.deny_list to null")
        return None
    if not isinstance(value, str) or not value:
        raise Fault(f"upstream.deny_list in the install manifest at {root} is not a path")
    path = Path(value).expanduser()
    return DenyList(path if path.is_absolute() else root / path)


# ------------------------------------------------------------------ output

class Out:
    def __init__(self):
        self.deny: DenyList | None = None
        self.seen: set[tuple[str, str]] = set()
        self.findings = 0

    def mask(self, text: str) -> str:
        norm = normalize(text)
        return self.deny.mask(norm) if self.deny else norm

    def note(self, text: str) -> None:
        print(f"leak-gate: {self.mask(text)}", flush=True)

    def finding(self, where: str, cls: str) -> None:
        line = f"{self.mask(where)} {cls}"
        if (line, cls) not in self.seen:
            self.seen.add((line, cls))
            self.findings += 1
            print(line, flush=True)


# ------------------------------------------------------------------- git

def git(args: list[str], cwd=None, check: bool = True) -> bytes:
    proc = subprocess.run(["git", *args], cwd=cwd, stdin=subprocess.DEVNULL,
                          capture_output=True)
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Fault(f"git {args[0]} failed (exit {proc.returncode}): {err[-1] if err else ''}")
    return proc.stdout


def toplevel() -> Path:
    try:
        return Path(git(["rev-parse", "--show-toplevel"]).decode().strip())
    except Fault:
        raise Fault("not inside a git work tree") from None


def resolve_commit(top: Path, rev: str) -> str:
    out = git(["rev-parse", "--verify", "-q", f"{rev}^{{commit}}"], cwd=top, check=False).strip()
    if not out:
        raise Fault(f"{rev!r} does not name a commit in this repository")
    return out.decode()


class Objects:
    """One `git cat-file --batch` process for every object read."""

    def __init__(self, top: Path):
        self.proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=top,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, rev: str, optional: bool = False) -> tuple[str, bytes] | None:
        """(type, data); with optional=True, None for a name that resolves to nothing."""
        self.proc.stdin.write(rev.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if optional and header[-1:] == [b"missing"]:
            return None
        if len(header) != 3:
            raise Fault(f"object {rev} cannot be read")
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return header[1].decode(), data

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


def raw_changes(out: bytes):
    """(status, dst mode, dst sha, dst path) per entry of a `--raw -z` diff."""
    fields = out.split(b"\0")
    i = 0
    while i < len(fields) and fields[i]:
        meta = fields[i].decode("ascii", "replace")
        if not meta.startswith(":"):
            raise Fault("unexpected git diff --raw output")
        _src_mode, dst_mode, _src_sha, dst_sha, status = meta[1:].split(" ")[:5]
        i += 1
        if status[:1] in ("R", "C"):
            i += 1
        yield status[:1], dst_mode, dst_sha, fields[i].decode("utf-8", "replace")
        i += 1


def parse_range(spec: str) -> tuple[str | None, str]:
    if spec.startswith(".."):
        raise Usage(f"--range {spec}: git reads ..<b> as HEAD..<b>; pass <a>..<b>, "
                    "or <b> alone for its whole history")
    if "..." in spec:
        raise Usage(f"--range {spec}: a symmetric range is not supported; pass <a>..<b>")
    base, sep, head = spec.partition("..")
    if not sep:
        return None, spec
    if not head:
        raise Usage(f"--range {spec}: no <b>")
    return (None if re.fullmatch(r"0+", base) else base), head


# --------------------------------------------------------------- scanning

def binary_strings(data: bytes):
    """(offset, text) for every run a reader of the bytes could see."""
    for m in PRINTABLE_RUN.finditer(data):
        yield m.start(), m.group().decode("utf-8", "replace")
    for m in UTF16_RUN.finditer(data):
        yield m.start(), m.group().decode("utf-16-le", "replace")
    if data.startswith(PNG_MAGIC):
        yield from png_compressed_text(data)


def _inflate(data: bytes) -> bytes | None:
    try:
        return zlib.decompressobj().decompress(data, INFLATE_LIMIT)
    except zlib.error:
        return None


def png_compressed_text(data: bytes):
    pos = len(PNG_MAGIC)
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        text = None
        if ctype == b"zTXt":
            _key, _, rest = body.partition(b"\0")
            text = _inflate(rest[1:])
        elif ctype == b"iTXt":
            _key, _, rest = body.partition(b"\0")
            if rest[:1] == b"\1":
                _lang, _, rest = rest[2:].partition(b"\0")
                _tkey, _, packed = rest.partition(b"\0")
                text = _inflate(packed)
        if text:
            for line in text.decode("utf-8", "replace").split("\n"):
                yield pos, line
        if ctype == b"IEND":
            break
        pos += 12 + length


def line_digest(data: bytes, lineno: int) -> str | None:
    lines = data.split(b"\n")
    return sha256_hex(lines[lineno - 1]) if 0 < lineno <= len(lines) else None


class Scanner:
    def __init__(self, out: Out, deny: DenyList | None, patterns, allowed):
        self.out = out
        self.deny = deny
        self.patterns = patterns
        self.allowed = allowed
        self.stats: collections.Counter = collections.Counter()
        self._blobs: dict[str, list] = {}
        self.blob_tree: BlobTree | None = None  # set while a git scope collects for gitleaks

    def classify(self, text: str) -> tuple[list[str], list[str]]:
        norm = normalize(text)
        deny = [f"deny#{n}" for n in self.deny.hits(norm)] if self.deny else []
        public = [cls for cls, rx in self.patterns if rx.search(norm)]
        return deny, public

    def report(self, where: str, deny: list[str], public: list[str], allow_key=None) -> None:
        if public and allow_key is not None and allow_key in self.allowed:
            self.stats["allowed lines"] += 1
            public = []
        for cls in dict.fromkeys(deny + public):
            self.out.finding(where, cls)

    def text(self, where: str, text: str) -> None:
        self.report(where, *self.classify(text))

    def analyze(self, data: bytes) -> list:
        rows = []
        text = None
        if b"\0" not in data:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        if text is not None:
            for n, raw in enumerate(data.split(b"\n"), 1):
                deny, public = self.classify(raw.decode("utf-8"))
                if deny or public:
                    rows.append((str(n), sha256_hex(raw), deny, public))
            return rows
        self.stats["binary blobs"] += 1
        for offset, run in binary_strings(data):
            deny, public = self.classify(run)
            if deny or public:
                rows.append((f"@{offset}", None, deny, public))
        return rows

    def content(self, where_prefix: str, path: str, data: bytes, key: str | None = None) -> None:
        rows = self._blobs.get(key) if key else None
        if rows is None:
            rows = self.analyze(data)
            if key:
                self._blobs[key] = rows
        self.stats["blobs"] += 1
        for loc, digest, deny, public in rows:
            self.report(f"{where_prefix}{path}:{loc}", deny, public,
                        (path, digest) if digest else None)

    def identity(self, where: str, ident: str) -> None:
        self.stats["identities"] += 1
        deny, public = self.classify(ident)
        self.report(where, deny, public + (["ai-identity"] if ai_identity(ident) else []))

    def entry(self, objs: Objects, where_prefix: str, path: str, mode: str, sha: str) -> None:
        self.stats["paths"] += 1
        self.text(f"{where_prefix}{path}:(path)", path)
        if mode == "160000" or re.fullmatch(r"0+", sha):
            return
        tree = self.blob_tree
        need = mode == "120000" or sha not in self._blobs or (tree is not None and not tree.has(path, sha))
        data = objs.read(sha)[1] if need else b""
        if mode == "120000":
            self.stats["symlinks"] += 1
            self.text(f"{where_prefix}{path}:(symlink)", data.decode("utf-8", "replace"))
        else:
            self.content(where_prefix, path, data, sha)
        if tree is not None:
            tree.add(where_prefix, path, sha, data)

    def commit(self, objs: Objects, top: Path, sha: str) -> None:
        self.stats["commits"] += 1
        short = sha[:12]
        _kind, data = objs.read(sha)
        header, _, message = data.partition(b"\n\n")
        parents = []
        for line in header.split(b"\n"):
            if line.startswith(b"parent "):
                parents.append(line[7:].decode())
            elif line.startswith((b"author ", b"committer ")):
                role, _, ident = line.decode("utf-8", "replace").partition(" ")
                self.identity(f"{short}:({role})", re.sub(r" \d+ [+-]\d{4}$", "", ident))
        self.message_lines(f"{short}:(message)", message)
        base = [parents[0], sha] if parents else ["--root", sha]
        out = git(["diff-tree", "-r", "-z", "--raw", "-M", "--no-abbrev", "--no-commit-id", *base], cwd=top)
        for status, mode, blob, path in raw_changes(out):
            if status != "D":
                self.entry(objs, f"{short}:", path, mode, blob)

    def tag(self, objs: Objects, sha: str) -> None:
        kind, data = objs.read(sha)
        if kind != "tag":
            return
        self.stats["tags"] += 1
        header, _, message = data.partition(b"\n\n")
        for line in header.split(b"\n"):
            if line.startswith(b"tagger "):
                ident = line.decode("utf-8", "replace")[len("tagger "):]
                self.identity(f"{sha[:12]}:(tagger)", re.sub(r" \d+ [+-]\d{4}$", "", ident))
        self.message_lines(f"{sha[:12]}:(tag message)", message)

    def message_lines(self, where: str, message: bytes) -> None:
        self.stats["messages"] += 1
        for n, line in enumerate(message.decode("utf-8", "replace").split("\n"), 1):
            self.text(f"{where}:{n}", line)


# ---------------------------------------------------------------- gitleaks

def gitleaks_exe() -> str:
    try:
        pinned = VERSION_FILE.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        raise Fault(f"{VERSION_FILE.name} cannot be read") from None
    exe = os.environ.get("FLEET_GITLEAKS") or shutil.which("gitleaks")
    if not exe:
        fallback = Path.home() / ".local" / "bin" / "gitleaks"
        exe = str(fallback) if os.access(fallback, os.X_OK) else None
    if not exe:
        raise Fault(f"gitleaks {pinned} is not installed: {INSTALL_HINT}")
    try:
        got = subprocess.run([exe, "version"], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=60).stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Fault(f"gitleaks at {exe} does not run: {type(exc).__name__}") from None
    if got.lstrip("v") != pinned.lstrip("v"):
        raise Fault(f"gitleaks at {exe} is version {got or '<none>'}; this repository pins "
                    f"{pinned}: {INSTALL_HINT}")
    if not GITLEAKS_CONFIG.is_file():
        raise Fault(f"{GITLEAKS_CONFIG.name} is missing beside {Path(__file__).name}; without it gitleaks "
                    "would read a configuration from the tree under scan")
    return exe


def run_gitleaks(exe: str, args: list[str], cwd: Path, stdin_bytes: bytes | None = None) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="leak-gate-") as scratch:
        report = os.path.join(scratch, "report.json")
        no_ignore = os.path.join(scratch, "no-ignore")
        os.mkdir(no_ignore)
        cmd = [exe, *args, "--config", str(GITLEAKS_CONFIG),
               "--no-banner", "--no-color", "--redact", "--ignore-gitleaks-allow",
               "--exit-code", str(GITLEAKS_LEAK_EXIT), "--report-format", "json",
               "--report-path", report, "--log-level", "error",
               "--gitleaks-ignore-path", no_ignore]
        env = {k: v for k, v in os.environ.items() if not k.startswith("GITLEAKS_")}
        feed = {"input": stdin_bytes} if stdin_bytes is not None else {"stdin": subprocess.DEVNULL}
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, env=env, **feed)
        if proc.returncode not in (0, GITLEAKS_LEAK_EXIT):
            err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise Fault(f"gitleaks {args[0]} failed (exit {proc.returncode}): {err[-1] if err else ''}")
        try:
            with open(report, encoding="utf-8") as fh:
                findings = json.load(fh)
        except FileNotFoundError:
            findings = []
        except (OSError, ValueError):
            raise Fault("the gitleaks report cannot be read") from None
    if proc.returncode == GITLEAKS_LEAK_EXIT and not findings:
        raise Fault("gitleaks reported leaks and wrote no finding")
    return findings if isinstance(findings, list) else []


def report_gitleaks(sc: Scanner, findings: list[dict], locate) -> None:
    """locate(finding) -> [(where, allow.txt path, data or None)], one row per place."""
    sc.stats["gitleaks runs"] += 1
    for f in findings:
        line = f.get("StartLine") or 0
        for where, path, data in locate(f):
            digest = line_digest(data, line) if data is not None else None
            sc.report(where, [], [f"gitleaks:{f.get('RuleID') or 'unknown'}"], (path, digest) if digest else None)


class BlobTree:
    """The blobs one git scope enumerated, written out for ONE `gitleaks dir` run.
    Each distinct (path, blob) gets `<slot>/<path>`, so a rule or allowlist that
    reads the path sees the real one, and a finding maps back to every place the
    scope met that blob at that path."""

    def __init__(self, root: Path):
        self.root = root
        self.slots: dict[tuple[str, str], str] = {}
        self.places: dict[str, tuple[str, list[str]]] = {}  # slot -> (path, [where prefix])

    def has(self, path: str, sha: str) -> bool:
        return (path, sha) in self.slots

    def add(self, where_prefix: str, path: str, sha: str, data: bytes) -> None:
        slot = self.slots.get((path, sha))
        if slot is None:
            parts = Path(path).parts
            if not parts or Path(path).is_absolute() or ".." in parts:
                raise Fault(f"{path}: a path git never records (empty, absolute or with ..)")
            slot = self.slots[(path, sha)] = str(len(self.slots))
            dest = self.root / slot / path
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            except OSError as exc:
                raise Fault(f"{path} cannot be written for gitleaks: {type(exc).__name__}") from None
            self.places[slot] = (path, [])
        self.places[slot][1].append(where_prefix)

    def locate(self, f: dict) -> list:
        rel = Path(f.get("File") or "")
        rel = rel.relative_to(self.root) if rel.is_absolute() else rel
        slot, _, _ = rel.as_posix().removeprefix("./").partition("/")
        if slot not in self.places:
            raise Fault("gitleaks reported a file the gate did not write")
        path, prefixes = self.places[slot]
        data = (self.root / slot / path).read_bytes()
        return [(f"{prefix}{path}:{f.get('StartLine')}", path, data) for prefix in prefixes]


def gitleaks_over_blobs(sc: Scanner, exe: str, enumerate_scope) -> None:
    """Run enumerate_scope() (which calls sc.entry for every blob it scans) with a
    BlobTree attached, then `gitleaks dir` over exactly those blobs."""
    with tempfile.TemporaryDirectory(prefix="leak-gate-blobs-") as scratch:
        tree = sc.blob_tree = BlobTree(Path(scratch))
        try:
            enumerate_scope()
        finally:
            sc.blob_tree = None
        report_gitleaks(sc, run_gitleaks(exe, ["dir", "."], tree.root), tree.locate)


# ------------------------------------------------------------------ scopes

def scope_staged(sc: Scanner, objs: Objects, top: Path, exe: str) -> None:
    out = git(["diff", "--cached", "--raw", "-z", "-M", "--no-abbrev", "--no-ext-diff"], cwd=top)

    def enumerate_scope():
        for status, mode, sha, path in raw_changes(out):
            if status != "D":
                sc.entry(objs, "", path, mode, sha)

    gitleaks_over_blobs(sc, exe, enumerate_scope)


def scope_commits(sc: Scanner, objs: Objects, top: Path, exe: str, rev_args: list[str],
                  allowed: set) -> None:
    def enumerate_scope():
        for sha in git(["rev-list", *rev_args], cwd=top).decode().split():
            sc.commit(objs, top, sha)

    saved, sc.allowed = sc.allowed, allowed
    try:
        gitleaks_over_blobs(sc, exe, enumerate_scope)
    finally:
        sc.allowed = saved


def scope_range(sc: Scanner, objs: Objects, top: Path, exe: str, spec: str) -> None:
    base, head = parse_range(spec)
    head_sha = resolve_commit(top, head)
    rev_args = [head_sha] if base is None else [f"{resolve_commit(top, base)}..{head_sha}"]
    head_obj = git(["rev-parse", "--verify", "-q", head], cwd=top, check=False).decode().strip()
    if head_obj:
        sc.tag(objs, head_obj)
    scope_commits(sc, objs, top, exe, rev_args, allow_at(objs, head_sha))


def scope_history(sc: Scanner, objs: Objects, top: Path, exe: str) -> None:
    allowed = allow_at(objs, "HEAD")
    for line in git(["for-each-ref", "--format=%(objectname) %(refname)"], cwd=top).decode().splitlines():
        sha, _, name = line.partition(" ")
        sc.stats["refs"] += 1
        sc.text(f"ref:{name}", name)
        sc.tag(objs, sha)
        allowed |= allow_at(objs, sha)
    scope_commits(sc, objs, top, exe, ["--all"], allowed)


def scope_tree(sc: Scanner, exe: str, root_arg: str) -> None:
    root = Path(root_arg).resolve()
    if not root.is_dir():
        raise Fault(f"--tree {root_arg}: not a directory")

    def unlisted(exc: OSError):
        # os.walk drops a directory it cannot list, and everything under it, silently
        where = os.path.relpath(exc.filename, root) if exc.filename else root_arg
        raise Fault(f"--tree: {where} cannot be listed ({type(exc).__name__}), so nothing under it "
                    "would be read")

    for dirpath, dirnames, filenames in os.walk(root, onerror=unlisted):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        rel_dir = Path(dirpath).relative_to(root)
        for name in dirnames + sorted(f for f in filenames if f != ".git"):
            full = Path(dirpath) / name
            rel = (rel_dir / name).as_posix()
            sc.stats["paths"] += 1
            sc.text(f"{rel}:(path)", rel)
            if full.is_symlink():
                sc.stats["symlinks"] += 1
                sc.text(f"{rel}:(symlink)", os.readlink(full))
            elif name in filenames and full.is_file():
                try:
                    data = full.read_bytes()
                except OSError as exc:
                    raise Fault(f"{rel} cannot be read: {type(exc).__name__}") from None
                sc.content("", rel, data)

    def locate(f):
        rel = os.path.relpath(os.path.join(root, f.get("File") or ""), root) \
            if not os.path.isabs(f.get("File") or "") else os.path.relpath(f["File"], root)
        rel = Path(rel).as_posix()
        try:
            data = (root / rel).read_bytes()
        except OSError:
            data = None
        return [(f"{rel}:{f.get('StartLine')}", rel, data)]

    report_gitleaks(sc, run_gitleaks(exe, ["dir", str(root)], root), locate)


def scope_message(sc: Scanner, exe: str, path: str) -> None:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise Fault(f"the message file {path} cannot be read: {type(exc).__name__}") from None
    kept = []
    for line in data.split(b"\n"):
        if SCISSORS.match(line.decode("utf-8", "replace")):
            break
        kept.append(line)
    message = b"\n".join(kept)
    sc.message_lines("message", message)
    report_gitleaks(sc, run_gitleaks(exe, ["stdin"], Path.cwd(), message),
                    lambda f: [(f"message:{f.get('StartLine')}", "", None)])


def scope_identity(sc: Scanner) -> None:
    for role, var in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        ident = git(["var", var]).decode("utf-8", "replace").strip()
        sc.identity(f"identity:({role})", re.sub(r" \d+ [+-]\d{4}$", "", ident))


def allow_entry(spec: str) -> int:
    path, _, line = spec.rpartition(":")
    if not path or not line.isdigit():
        raise Usage("--allow-entry wants <path>:<line number>")
    digest = line_digest(Path(path).read_bytes(), int(line))
    if digest is None:
        raise Usage(f"{path} has no line {line}")
    print(f"{path}:{digest}")
    return OK


# -------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leak_gate.py", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--range", dest="ranges", action="append", default=[], metavar="A..B")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--tree", dest="trees", action="append", default=[], metavar="DIR")
    ap.add_argument("--message", dest="messages", action="append", default=[], metavar="FILE")
    ap.add_argument("--identity", action="store_true")
    ap.add_argument("--ref", dest="refs", action="append", default=[], metavar="NAME")
    ap.add_argument("--ci", action="store_true")
    ap.add_argument("--allow-entry", metavar="PATH:LINE")
    args = ap.parse_args(argv)
    out = Out()
    try:
        if args.allow_entry:
            return allow_entry(args.allow_entry)
        git_scopes = args.staged or args.ranges or args.history
        needs_gitleaks = git_scopes or args.trees or args.messages
        if not (needs_gitleaks or args.identity or args.refs):
            ap.error("name at least one scope")
        for spec in args.ranges:
            parse_range(spec)
        patterns, allowed = load_patterns(), load_allow()
        deny = resolve_deny(args.ci, out)
        if deny:
            out.deny = deny
            out.note(f"deny list: {len(deny.entries)} entries ({deny.path})")
        exe = gitleaks_exe() if needs_gitleaks else ""
        sc = Scanner(out, deny, patterns, allowed)
        top = toplevel() if (git_scopes or args.identity) else None
        objs = Objects(top) if git_scopes else None
        try:
            if args.staged:
                scope_staged(sc, objs, top, exe)
            for spec in args.ranges:
                scope_range(sc, objs, top, exe, spec)
            if args.history:
                scope_history(sc, objs, top, exe)
        finally:
            if objs:
                objs.close()
        for tree in args.trees:
            scope_tree(sc, exe, tree)
        for msg in args.messages:
            scope_message(sc, exe, msg)
        if args.identity:
            scope_identity(sc)
        for name in args.refs:
            sc.stats["refs"] += 1
            sc.text(f"ref:{name}", name)
    except Usage as exc:
        print(f"leak-gate: usage: {out.mask(str(exc))}", file=sys.stderr)
        return USAGE
    except Fault as exc:
        print(f"leak-gate: FAULT: {out.mask(str(exc))}", file=sys.stderr)
        print("leak-gate: no verdict - the subject was not judged", file=sys.stderr)
        return FAULT
    scanned = ", ".join(f"{v} {k}" for k, v in sorted(sc.stats.items())) or "nothing"
    if out.findings:
        out.note(f"{out.findings} finding(s). scanned: {scanned}")
        out.note("deny#<n> is line n of the private deny list (never print the value); a line "
                 "that trips a public pattern by design goes in tools/leak-gate/allow.txt "
                 "(--allow-entry <path>:<line> prints its entry)")
        return FINDING
    out.note(f"clean. scanned: {scanned}")
    return OK


if __name__ == "__main__":
    sys.exit(main())
