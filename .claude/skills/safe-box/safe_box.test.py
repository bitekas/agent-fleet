#!/usr/bin/env python3
"""safe_box.test.py - safe_box.py driven end to end over real sockets on 127.0.0.1.

    python3 .claude/skills/safe-box/safe_box.test.py

Hermetic: every run gets a fresh temporary tree (a fleet secrets directory, an
agents root with one agent home, a host settings file, an "outside" directory
and its own TMPDIR), selected through FLEET_SECRETS_DIR and FLEET_HOST_CONFIG,
so no real install, host config or secret is read or written. Prints one line
per check and ALL CHECKS PASSED, or names every failure and exits 1.

WHAT EACH CHECK MEASURES. Every failure line starts with a TAG; the tag is what
the broken copies below are matched against.

  happy        two secrets, one under each allowed root, both parents missing:
               the form is one password field per name and POSTs (form), one
               submission writes both files with EXACTLY the submitted bytes
               (bytes) at mode 600 (mode), every directory it created is 700
               (dirs), no temp file is left beside them or anywhere else in the
               tree (leak-files), no submitted value reaches stdout or stderr
               (leak-output), the URL path appears only in the READY and open:
               lines (leak-path), and the process exits 0 by itself
               (exit-complete).
  notfound     a wrong path, a wrong code and a foreign Host header each get
               404 and write nothing; the --max-refused-th refusal ends the
               session with exit 1 (limit).
  undeclared   a submission with the right code that carries an undeclared name
               is refused and writes nothing; while the server is alive and
               holding the values it received, neither it nor any descendant
               carries a value in its command line or environment (leak-proc).
               The process is read through fleetlib.services (procfs on Linux,
               the kernel's sysctl on macOS) and the tree through `ps`. ⚠️ ON
               MACOS THE ENVIRONMENT HALF IS NOT MEASURED: macOS shows no
               process's environment, not even a child's, so the command line
               is the whole of leak-proc there, and the run says so.
  roots        `..` inside the root, `..` leaving it, an absolute path
               elsewhere, a directory and a file symlink pointing out, a home's
               secrets directory that is not secrets/personal, a personal
               directory of no existing agent home, and one under a directory
               of the agents root that is no agent's home (a knowledge store,
               the claims directory: neither holds an agent's .claude config
               directory): each is refused at startup, exit 2, no READY line,
               nothing written, and the last two by --dry-run as well.
  existing     an existing file without --replace is refused at startup; a file
               that appears AFTER startup is not overwritten by the submission;
               --replace overwrites, at mode 600.
  exit-timeout with no request the session ends at --timeout, exit 1.
  bind         the server answers on 127.0.0.1 and refuses a connection at
               every other local address the test can reach (127.0.0.2 and a
               non-loopback interface address).

POSITIVE CONTROLS - DO NOT REMOVE. A check whose instrument cannot see the
defect reports a clean result for the wrong reason, so each instrument is first
shown to see something known to be there. If a control does not fire, the check
reports `<tag>: NO VERDICT`, which fails the run and never counts as a pass:
  * the leak search finds the value in the file it was written to, and in its
    own form encoding, before its silence about stdout, stderr and other files
    means anything;
  * the process reader finds a decoy value in the cmdline AND (where the
    platform shows it) the environment of a decoy `sleep`, and the descendant
    walk finds that decoy under this process, before its silence about the
    server's tree means anything;
  * the bind probe reaches, at each other address, a wildcard listener this
    test opens itself, before a refused connection to the server at that
    address means the server's bind and not an address that routes nowhere;
  * the 404 checks first see the right path answer 200;
  * the root refusals first see two valid declarations pass --dry-run, so an
    exit 2 below is about the path, not a startup crash.

THE BROKEN COPIES - DO NOT REMOVE. MUTANTS lists, for each property the script
claims, a copy of safe_box.py with that property broken (bind 0.0.0.0, mode 644,
no path check, the default request log back on, a value handed to a child
process, ...) and the TAG that copy must fail. Every copy is run through the
check that owns its tag, and must produce a failure with THAT tag that is not a
NO VERDICT: a copy that passes, or fails only for some other reason, means the
check is blind to the defect it is named for, and the run fails. Each anchor
must occur exactly once in safe_box.py; one that does not is a failure too,
because a stale anchor leaves a copy identical to the original and its control
then measures nothing. When safe_box.py is changed, move the anchors with it.

What no check here covers: a value that reaches a child process which has
exited before the process sample is taken (the script starts no process at all,
and the sample cannot prove the past); a value in a process's environment on macOS
(see leak-proc); a file written under a looser mode and
narrowed afterwards (the final mode cannot show the window, which is why the
script creates it 0600 and the review of any change to write_one() must look);
a browser's own handling of the page.
"""

import http.client
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "safe_box.py"
LIB = HERE.parents[2] / "lib"
sys.path.insert(0, str(LIB))
from fleetlib import services  # noqa: E402 - the process readers, procfs or sysctl

VALUE_A = "fixture one é☃ =&+% end"   # non-ASCII, spaces and characters a form encodes
VALUE_B = "fixture-two-plain"
VALUE_P = "procmarker-declared-0123"
VALUE_Q = "procmarker-undeclared-4567"
DECOY = "decoymarker-8901"


# ---------------------------------------------------------------- harness

class World:
    """A fresh tree: secrets/ (FLEET_SECRETS_DIR, not created), agents/ada/ (an
    agent home: it holds ada's Claude Code config directory, .claude, as the
    install makes it), outside/, tmpdir/ (TMPDIR) and host.json
    (FLEET_HOST_CONFIG, whose claims_dir is agents/claims, the default layout)."""

    def __init__(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="fleet-safe-box-test-")))
        self.secrets = self.root / "secrets"
        self.agents = self.root / "agents"
        self.home = self.agents / "ada"
        self.personal = self.home / "secrets" / "personal"
        self.outside = self.root / "outside"
        self.tmpdir = self.root / "tmpdir"
        for d in (self.home / ".claude", self.outside, self.tmpdir):
            d.mkdir(parents=True)
        self.host = self.root / "host.json"
        self.host.write_text(json.dumps({"schema": 1, "agents_root": str(self.agents),
                                         "fleet_checkout": str(self.root / "fleet"),
                                         "claims_dir": str(self.agents / "claims")}))
        self.env = {k: v for k, v in os.environ.items() if k not in ("FLEET_CONTEXT_ROOT",)}
        self.env.update(FLEET_SECRETS_DIR=str(self.secrets), FLEET_HOST_CONFIG=str(self.host),
                        TMPDIR=str(self.tmpdir), PYTHONDONTWRITEBYTECODE="1")

    def files(self):
        return [p for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()]

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Server:
    """One safe_box.py process with its stdout and stderr read as they arrive."""

    def __init__(self, script, world, *args):
        # umask 0: every mode this test asserts is then the script's own doing.
        # Under the usual 022 a directory made by a bare makedirs() is 755 and
        # fails anyway, but a file opened 0666 and a directory made 0777 would
        # read as narrower than the script asked for, and a umask of 077 would
        # pass both.
        # PYTHONFAULTHANDLER: a server that never says READY is sent SIGABRT
        # (wait_ready), and faulthandler prints where each of its threads was stuck
        # to the stderr the NO VERDICT line quotes, instead of an empty one.
        self.p = subprocess.Popen([sys.executable, str(script), *args], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=dict(world.env, PYTHONFAULTHANDLER="1"), cwd=world.root, umask=0)
        self.out, self.err = [], []
        self.ready = threading.Event()
        self.eof = threading.Event()
        self.port = self.path = self.code = None
        self.readers = [threading.Thread(target=self._read, args=(self.p.stdout, self.out, True), daemon=True),
                        threading.Thread(target=self._read, args=(self.p.stderr, self.err, False), daemon=True)]
        for t in self.readers:
            t.start()

    def _read(self, stream, sink, is_stdout):
        for raw in iter(stream.readline, b""):
            sink.append(raw)
            m = re.match(rb"SAFE-BOX READY port=(\d+) path=(\S+) code=(\S+) ", raw) if is_stdout else None
            if m:
                self.port, self.path, self.code = int(m.group(1)), m.group(2).decode(), m.group(3).decode()
                self.ready.set()
        if is_stdout:
            self.eof.set()

    def wait_ready(self, secs=15):
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline and not self.ready.is_set() and not self.eof.is_set():
            self.ready.wait(0.05)
        if not self.ready.is_set() and self.p.poll() is None:
            self.p.send_signal(signal.SIGABRT)      # faulthandler: the stuck stack, on stderr
            self.eof.wait(5)
            for t in self.readers:
                t.join(2)
        return self.ready.is_set()

    def request(self, method, path, fields=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host} if host else {}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            return r.status, r.read(), r
        except OSError as exc:
            return None, str(exc).encode(), None
        finally:
            conn.close()

    def wait_exit(self, secs):
        try:
            return self.p.wait(secs)
        except subprocess.TimeoutExpired:
            return None

    def stop(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        for t in self.readers:
            t.join(5)

    @property
    def stdout(self):
        return b"".join(self.out).decode("utf-8", "replace")

    @property
    def stderr(self):
        return b"".join(self.err).decode("utf-8", "replace")


def forms(value):
    """Every encoding in which a submitted value could leak: as written, and as
    a form body carries it."""
    return {value.encode("utf-8"), urllib.parse.quote_plus(value).encode(), urllib.parse.quote(value).encode()}


def found(blob, value):
    return any(f in blob for f in forms(value))


def proc_blobs(pid):
    """(cmdline, environ) of a live process as NUL-joined bytes, or None when it is
    gone. environ is None where the platform does not show it (macOS:
    services.proc_env), which is NOT an empty environment.

    Waits (up to 5 s) for a non-empty cmdline. Python starts a child with vfork,
    which releases the parent as soon as the child's exec replaces its memory,
    BEFORE the kernel records where the new argv and environment are: read in
    that window, both are empty, and an empty read is a clean result for the
    wrong reason. Measured on Linux 7.0: 18 of 20 reads taken straight after
    Popen() returned were empty. Every live user process has a non-empty
    cmdline, so empty means "not yet", never "nothing there"."""
    deadline = time.monotonic() + 5
    while True:
        argv = services.proc_argv(pid)
        if argv is None:
            return None
        if argv or time.monotonic() > deadline:
            env = services.proc_env(pid)
            return ("\0".join(argv).encode(),
                    None if env is None else "\0".join(f"{k}={v}" for k, v in env.items()).encode())
        time.sleep(0.01)


def descendants(pid):
    """Every live descendant of `pid`, from each process's parent as POSIX `ps`
    lists it (the same on Linux and macOS)."""
    children = {}
    out = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], capture_output=True, text=True,
                         check=True).stdout
    for line in out.splitlines():
        if len(line.split()) == 2:
            child, ppid = map(int, line.split())
            children.setdefault(ppid, []).append(child)
    out, todo = [], [pid]
    while todo:
        for c in children.get(todo.pop(), []):
            out.append(c)
            todo.append(c)
    return out


def connects(addr, port):
    try:
        socket.create_connection((addr, port), timeout=2).close()
        return True
    except OSError:
        return False


def other_addresses():
    """Local addresses other than 127.0.0.1: 127.0.0.2 (Linux routes all of
    127/8 to lo) and the interface address of the default route, found by a UDP
    connect, which sends nothing."""
    addrs = ["127.0.0.2"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            a = s.getsockname()[0]
            if not a.startswith("127."):
                addrs.append(a)
    except OSError:
        pass
    return addrs


def wrong_code(code):
    first = "B" if code[0] != "B" else "C"
    return first + code[1:]


# ----------------------------------------------------------------- checks

def check_happy(script):
    f = []
    w = World()
    try:
        pa = w.personal / "chat-token"
        rel = "sub/dir/api.key"
        pb = w.secrets / rel
        s = Server(script, w, "--timeout", "30", f"chat-token={pa}", f"api-key={rel}")
        try:
            if not s.wait_ready():
                return [f"happy: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            st, page, r = s.request("GET", s.path)
            text = page.decode("utf-8", "replace")
            if st != 200:
                f.append(f"happy: the form answered {st}, not 200")
            if text.count('type="password"') != 2 or "chat-token" not in text or "api-key" not in text:
                f.append("happy: the form is not one password field per declared name")
            if '<form method="post"' not in text:
                f.append("form: the form does not submit by POST, so its values would travel in the URL")
            if r is None or r.getheader("Cache-Control") != "no-store":
                f.append("happy: the form is not served with Cache-Control: no-store")
            st, _, _ = s.request("POST", s.path, [("code", s.code), ("s-chat-token", VALUE_A),
                                                  ("s-api-key", VALUE_B)])
            if st != 200:
                f.append(f"happy: the submission answered {st}, not 200")
            rc = s.wait_exit(10)
            if rc != 0:
                f.append(f"exit-complete: the session did not end by itself with exit 0 after its "
                         f"submission (exit {rc})")
        finally:
            s.stop()
        out = s.stdout
        for path, value in ((pa, VALUE_A), (pb, VALUE_B)):
            try:
                data, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                f.append(f"happy: {path.name} was not written: {exc.strerror}")
                continue
            if data != value.encode("utf-8"):
                f.append(f"bytes: {path.name} does not hold exactly the submitted bytes")
            if mode != 0o600:
                f.append(f"mode: {path.name} is mode {mode:o}, not 600")
            name = "chat-token" if path == pa else "api-key"
            if f"{name}: written ({len(value.encode('utf-8'))} bytes) {path}" not in out:
                f.append(f"happy: no `{name}: written (<size> bytes) <path>` line with the real size")
        for d in (w.secrets, w.secrets / "sub", w.secrets / "sub" / "dir", w.home / "secrets", w.personal):
            mode = stat.S_IMODE(d.stat().st_mode) if d.is_dir() else None
            if mode != 0o700:
                f.append(f"dirs: {d.relative_to(w.root)} was created with mode {mode and format(mode, 'o')}, not 700")
        if "SAFE-BOX END complete written=2/2" not in out:
            f.append("happy: no `SAFE-BOX END complete written=2/2` line")
        if pa.parent.is_dir() and pb.parent.is_dir():
            left = sorted(set(os.listdir(pa.parent)) - {pa.name}) + sorted(set(os.listdir(pb.parent)) - {pb.name})
            if left:
                f.append(f"leak-files: files left beside the destinations: {left}")
        # The leak search, after its control: it must find the value where it is known to be.
        body = urllib.parse.urlencode([("s", VALUE_A)]).encode()
        if not (pa.is_file() and found(pa.read_bytes(), VALUE_A) and found(body, VALUE_A)):
            f.append("leak-output: NO VERDICT, the leak search does not find the value in its own file "
                     "or in a form body, so its silence below would mean nothing")
        else:
            blob = b"".join(s.out) + b"".join(s.err)
            for value in (VALUE_A, VALUE_B):
                if found(blob, value):
                    f.append("leak-output: a submitted value appears in stdout or stderr")
                for p in w.files():
                    if p not in (pa, pb) and found(p.read_bytes(), value):
                        f.append(f"leak-files: a submitted value is in {p.relative_to(w.root)}")
        token = s.path.strip("/") if s.path else None
        for line in (s.stdout + s.stderr).splitlines():
            if token and token in line and not line.startswith(("SAFE-BOX READY ", "open: ")):
                f.append("leak-path: the URL path is printed outside the READY and open: lines")
                break
    finally:
        w.close()
    return f


def check_not_found(script):
    f = []
    w = World()
    try:
        target = w.secrets / "tok"
        s = Server(script, w, "--timeout", "30", "--max-refused", "4", f"tok={target}")
        try:
            if not s.wait_ready():
                return [f"notfound: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            st, _, _ = s.request("GET", s.path)
            if st != 200:
                return [f"notfound: NO VERDICT, the right path answered {st}, so a 404 elsewhere means nothing"]
            right = [("code", s.code), ("s-tok", VALUE_B)]
            wrong = [
                ("GET of the root", "GET", "/", None, None),
                ("a POST to a wrong path with the right code", "POST", f"/{secrets.token_urlsafe(24)}/", right, None),
                ("a POST with a wrong code", "POST", s.path, [("code", wrong_code(s.code)), ("s-tok", VALUE_B)], None),
                ("a POST with a foreign Host header", "POST", s.path, right, "attacker.example"),
            ]
            for i, (label, method, path, fields, host) in enumerate(wrong, 1):
                st, _, _ = s.request(method, path, fields, host)
                if st != 404:
                    f.append(f"notfound: {label} answered {st}, not 404")
                if target.exists():
                    f.append(f"notfound: {label} wrote the file")
                    break
                if i < len(wrong) and s.p.poll() is not None:
                    f.append(f"limit: the session ended after {i} refused requests, before --max-refused 4")
                    break
            rc = s.wait_exit(8)
            if rc != 1 or "SAFE-BOX END too-many-refused written=0/1" not in s.stdout:
                f.append(f"limit: the session did not end after --max-refused refused requests (exit {rc})")
        finally:
            s.stop()
        if target.exists() and not any(x.startswith("notfound:") for x in f):
            f.append("notfound: the file was written")
    finally:
        w.close()
    return f


def check_undeclared(script):
    f = []
    w = World()
    decoy = None
    try:
        target = w.secrets / "tok"
        s = Server(script, w, "--timeout", "30", f"tok={target}")
        try:
            if not s.wait_ready():
                return [f"undeclared: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            st, _, _ = s.request("POST", s.path, [("code", s.code), ("s-tok", VALUE_P), ("s-other", VALUE_Q)])
            written = [p.relative_to(w.root) for p in w.files() if p != w.host]
            if st != 400 or written:
                f.append(f"undeclared: a submission carrying an undeclared name answered {st} and wrote "
                         f"{len(written)} file(s); it must be refused (400) and write nothing")
            # leak-proc: the server has received both values and is still serving.
            if s.p.poll() is not None:
                f.append("leak-proc: NO VERDICT, the server is not alive after receiving the values")
                return f
            decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", DECOY],
                                     env=dict(w.env, SAFE_BOX_DECOY=DECOY),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            seen = proc_blobs(decoy.pid)
            env_read = seen is not None and seen[1] is not None
            if not (seen and DECOY.encode() in seen[0]
                    and (DECOY.encode() in seen[1] if env_read else sys.platform == "darwin")
                    and decoy.pid in descendants(os.getpid())):
                f.append("leak-proc: NO VERDICT, the process reader does not see a decoy value in a "
                         "decoy process's cmdline and environment, or the descendant walk misses the decoy")
                return f
            if not env_read:
                print("  leak-proc: the environment half is NOT MEASURED here: this platform shows no "
                      "process's environment; the command line was checked")
            tree = [s.p.pid] + descendants(s.p.pid)
            for pid in tree:
                blobs = proc_blobs(pid)
                if blobs and any(found(b, v) for b in blobs if b is not None for v in (VALUE_P, VALUE_Q)):
                    f.append(f"leak-proc: {'the server' if pid == s.p.pid else 'a child of the server'} "
                             f"carries a submitted value in its cmdline or environment")
        finally:
            s.stop()
    finally:
        if decoy is not None:
            decoy.kill()
            decoy.wait()
        w.close()
    return f


def check_roots(script):
    f = []
    w = World()
    try:
        w.secrets.mkdir(mode=0o700)
        (w.secrets / "link").symlink_to(w.outside)
        (w.secrets / "file-link").symlink_to(w.outside / "f2")
        # Directories of the agents root that are no agent's home: they exist, and
        # hold no .claude. Each must be refused by --dry-run and by a real start.
        knowledge, claims = w.agents / "knowledge", w.agents / "claims"
        (knowledge / "topic").mkdir(parents=True)
        (knowledge / "index.md").write_text("# index\n")
        claims.mkdir(mode=0o700)
        strays = [("a knowledge store under the agents root", [f"x={knowledge}/secrets/personal/f"]),
                  ("the claims directory under the agents root", [f"x={claims}/secrets/personal/f"])]
        ok = subprocess.run([sys.executable, str(script), "--dry-run", f"a={w.secrets}/ok", f"b={w.personal}/ok"],
                            env=w.env, cwd=w.root, capture_output=True, text=True, timeout=30)
        if (ok.returncode != 0 or f"would write: a -> {w.secrets}/ok" not in ok.stdout
                or f"would write: b -> {w.personal}/ok" not in ok.stdout or "READY" in ok.stdout
                or (w.secrets / "ok").exists()):
            return [f"roots: NO VERDICT, two valid declarations do not pass --dry-run cleanly "
                    f"(exit {ok.returncode}): {ok.stderr.strip()}"]
        cases = [
            ("a '..' that stays inside the root", [f"x={w.secrets}/a/../b"]),
            ("a relative '..' that leaves the root", ["x=../outside/f"]),
            ("an absolute path elsewhere", [f"x={w.outside}/f"]),
            ("a directory symlink pointing out", [f"x={w.secrets}/link/f"]),
            ("a file symlink pointing out", ["--replace", f"x={w.secrets}/file-link"]),
            ("a home's secrets directory that is not secrets/personal", [f"x={w.home}/secrets/other/f"]),
            ("the personal directory of no existing agent home", [f"x={w.agents}/nobody/secrets/personal/f"]),
        ] + strays
        for label, args in cases:
            s = Server(script, w, "--timeout", "3", *args)
            try:
                rc = s.wait_exit(15)
            finally:
                s.stop()
            if s.ready.is_set():
                f.append(f"roots: {label} was accepted and served")
            elif rc != 2 or "refused" not in s.stderr:
                f.append(f"roots: {label} exited {rc}, not 2 with a refusal")
            if any(w.outside.iterdir()) or (w.secrets / "b").exists() or (w.home / "secrets").exists() \
                    or (knowledge / "secrets").exists() or (claims / "secrets").exists():
                f.append(f"roots: {label} wrote a file or directory")
        for label, args in strays:
            dry = subprocess.run([sys.executable, str(script), "--dry-run", *args], env=w.env, cwd=w.root,
                                 capture_output=True, text=True, timeout=30)
            if dry.returncode != 2 or "refused" not in dry.stderr or "would write" in dry.stdout:
                f.append(f"roots: --dry-run accepts {label} (exit {dry.returncode}): {dry.stdout.strip()[-200:]}")
    finally:
        w.close()
    return f


def check_existing(script):
    f = []
    w = World()
    try:
        w.secrets.mkdir(mode=0o700)
        old = w.secrets / "tok"
        old.write_bytes(b"old value\n")
        s = Server(script, w, "--timeout", "3", f"tok={old}")
        try:
            rc = s.wait_exit(15)
        finally:
            s.stop()
        if s.ready.is_set() or rc != 2:
            f.append("existing: an existing file without --replace was not refused at startup")
        if old.read_bytes() != b"old value\n":
            f.append("existing: an existing file was changed without --replace")

        late = w.secrets / "late"
        s = Server(script, w, "--timeout", "30", f"late={late}")
        try:
            if not s.wait_ready():
                return f + [f"existing: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            late.write_bytes(b"appeared later\n")
            s.request("POST", s.path, [("code", s.code), ("s-late", VALUE_B)])
            rc = s.wait_exit(10)
        finally:
            s.stop()
        if late.read_bytes() != b"appeared later\n":
            f.append("existing: a file that appeared after startup was overwritten without --replace")
        elif rc != 1 or f"late: NOT written" not in s.stdout:
            f.append(f"existing: a file that appeared after startup is not reported NOT written, exit 1 (exit {rc})")

        s = Server(script, w, "--timeout", "30", "--replace", f"tok={old}")
        try:
            if not s.wait_ready():
                return f + [f"existing: NO VERDICT, no READY line with --replace; stderr: {s.stderr.strip()}"]
            s.request("POST", s.path, [("code", s.code), ("s-tok", VALUE_B)])
            rc = s.wait_exit(10)
        finally:
            s.stop()
        if rc != 0 or old.read_bytes() != VALUE_B.encode() or stat.S_IMODE(old.stat().st_mode) != 0o600:
            f.append(f"existing: --replace did not overwrite the file at mode 600 (exit {rc})")
    finally:
        w.close()
    return f


def check_timeout(script):
    f = []
    w = World()
    try:
        target = w.secrets / "tok"
        s = Server(script, w, "--timeout", "1", f"tok={target}")
        try:
            if not s.wait_ready():
                return [f"exit-timeout: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            rc = s.wait_exit(10)
        finally:
            s.stop()
        if rc != 1 or "SAFE-BOX END timeout written=0/1" not in s.stdout:
            f.append(f"exit-timeout: the session did not end by itself at --timeout (exit {rc})")
        if target.exists():
            f.append("exit-timeout: a file was written with no submission")
    finally:
        w.close()
    return f


def check_bind(script):
    f = []
    w = World()
    try:
        s = Server(script, w, "--timeout", "30", f"tok={w.secrets}/tok")
        try:
            if not s.wait_ready():
                return [f"bind: NO VERDICT, no READY line; stderr: {s.stderr.strip()}"]
            if not connects("127.0.0.1", s.port):
                return ["bind: NO VERDICT, the server does not answer on 127.0.0.1"]
            probed = 0
            for addr in other_addresses():
                ctl = socket.socket()
                try:
                    ctl.bind(("0.0.0.0", 0))
                    ctl.listen(1)
                    reachable = connects(addr, ctl.getsockname()[1])
                finally:
                    ctl.close()
                if not reachable:
                    continue
                probed += 1
                if connects(addr, s.port):
                    f.append("bind: the server accepts a connection at a local address other than 127.0.0.1")
            if probed == 0:
                f.append("bind: NO VERDICT, no other local address reaches even a wildcard listener")
        finally:
            s.stop()
    finally:
        w.close()
    return f


CHECKS = {
    "happy": check_happy, "notfound": check_not_found, "undeclared": check_undeclared,
    "roots": check_roots, "existing": check_existing, "exit-timeout": check_timeout, "bind": check_bind,
}

# (id, the tag its broken copy must fail, the check that owns the tag, [(anchor, replacement)...])
MUTANTS = [
    ("bind-wildcard", "bind", "bind", [('BIND = "127.0.0.1"', 'BIND = "0.0.0.0"')]),
    ("file-mode-644", "mode", "happy", [("FILE_MODE = 0o600", "FILE_MODE = 0o644")]),
    ("dir-mode-755", "dirs", "happy", [("DIR_MODE = 0o700", "DIR_MODE = 0o755")]),
    ("bytes-newline", "bytes", "happy", [('data = values[e.name].encode("utf-8")',
                                          'data = values[e.name].encode("utf-8") + b"\\n"')]),
    ("form-get", "form", "happy", [('<form method="post"', '<form method="get"')]),
    ("no-exit-on-complete", "exit-complete", "happy", [('box.end("complete")', "pass")]),
    ("value-printed", "leak-output", "happy", [("write_one(e, data, self.replace)",
                                                'write_one(e, data, self.replace); say(f"debug {values[e.name]}")')]),
    ("request-log-on", "leak-path", "happy", [("def log_message(", "def _quiet_log_message(")]),
    ("temp-in-tmpdir", "leak-files", "happy", [("tmp = os.path.join(parent, f\".",
                                                "tmp = os.path.join(os.environ[\"TMPDIR\"], f\"."),
                                               ("os.unlink(tmp)", "pass")]),
    ("any-code", "notfound", "notfound", [("return hmac.compare_digest(given.encode(), self.code.encode())",
                                           "return True")]),
    ("any-path", "notfound", "notfound", [("return hmac.compare_digest(path.encode(), self.path.encode())",
                                           "return True")]),
    ("any-host", "notfound", "notfound", [("return hostname in LOCAL_HOSTS and self.server.box.path_ok(path)",
                                           "return self.server.box.path_ok(path)")]),
    ("no-refusal-limit", "limit", "notfound", [("if n >= box.max_refused:", "if False:")]),
    ("undeclared-ignored", "undeclared", "undeclared", [('if not (key.startswith("s-") and key[2:] in box.names):',
                                                          'if not key.startswith("s-"):')]),
    ("value-to-child", "leak-proc", "undeclared", [(
        "body = self.rfile.read(length)",
        'body = self.rfile.read(length); __import__("subprocess").Popen([sys.executable, "-c", '
        '"import time; time.sleep(5)", body.decode()], env=dict(os.environ, SAFE_BOX_BODY=body.decode()))')]),
    ("dotdot-allowed", "roots", "roots", [('if ".." in raw.split("/"):', "if False:")]),
    ("no-prefix-check", "roots", "roots", [("allowed = fleet is not None and within(dest, fleet)", "allowed = True")]),
    ("no-symlink-resolve", "roots", "roots", [("dest = os.path.realpath(path)", "dest = os.path.abspath(path)")]),
    ("any-home-subdirectory", "roots", "roots", [("tuple(parts[1:3]) == PERSONAL", "True")]),
    ("no-home-existence", "roots", "roots", [('and os.path.isdir(os.path.join(agents, parts[0], ".claude")))', ")")]),
    ("any-agents-root-directory", "roots", "roots", [('os.path.join(agents, parts[0], ".claude")',
                                                      "os.path.join(agents, parts[0])")]),
    ("existing-not-refused", "existing", "existing", [("if not replace:", "if False:")]),
    ("clobbering-write", "existing", "existing", [("os.link(tmp, entry.path)", "os.replace(tmp, entry.path)")]),
    ("no-timeout", "exit-timeout", "exit-timeout", [("box.done.wait(args.timeout)", "box.done.wait()")]),
]


def report(label, failures):
    if failures:
        for x in failures:
            print(f"FAIL - {label}: {x}")
    else:
        print(f"ok   - {label}")


def main():
    total = []
    for name, fn in CHECKS.items():
        fails = fn(SCRIPT)
        report(f"{name} (safe_box.py)", fails)
        total += fails
    if total:
        print("NO VERDICT on the broken copies: safe_box.py itself fails, so a broken copy failing means nothing")
    else:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = Path(tempfile.mkdtemp(prefix="fleet-safe-box-mutants-"))
        try:
            skill = tree / "fleet" / ".claude" / "skills" / "safe-box"
            skill.mkdir(parents=True)
            (tree / "fleet" / "lib").symlink_to(LIB)
            for mid, tag, check, edits in MUTANTS:
                text, stale = source, []
                for anchor, replacement in edits:
                    if text.count(anchor) != 1:
                        stale.append(anchor)
                    text = text.replace(anchor, replacement, 1)
                if stale:
                    total.append(f"broken copy {mid}: anchor not found exactly once in safe_box.py: {stale}")
                    print(f"FAIL - broken copy {mid}: the anchor {stale[0]!r} is not in safe_box.py exactly once; "
                          f"move it with the code, or this control measures nothing")
                    continue
                copy = skill / "safe_box.py"
                copy.write_text(text, encoding="utf-8")
                fails = CHECKS[check](copy)
                hit = [x for x in fails if x.startswith(f"{tag}:") and "NO VERDICT" not in x]
                if hit:
                    print(f"ok   - broken copy {mid} fails {tag}: {hit[0][len(tag) + 2:]}")
                else:
                    msg = (f"broken copy {mid} does not fail {tag}; the {check} check is blind to it"
                           + (f" (it failed only: {fails})" if fails else ""))
                    print(f"FAIL - {msg}")
                    total.append(msg)
        finally:
            shutil.rmtree(tree, ignore_errors=True)
    if total:
        print(f"{len(total)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
