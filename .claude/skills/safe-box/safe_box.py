#!/usr/bin/env python3
"""safe_box.py - receive declared secrets through a one-time web form on
127.0.0.1 and write each one to the file declared for it.

Usage:
  safe_box.py [--timeout SECONDS] [--port PORT] [--max-refused N] [--replace]
              [--ssh-host HOST] [--dry-run] NAME=PATH [NAME=PATH ...]

  NAME=PATH     one expected secret: the label the form shows, and the file the
                value is written to. NAME matches [A-Za-z0-9][A-Za-z0-9._-]*
                (at most 64 characters). PATH may start with ~; a relative
                PATH resolves against the fleet secrets directory.
  --timeout     seconds the form stays open (default 600, at most 3600).
  --port        the port to listen on; 0, the default, takes a free one.
  --max-refused refused requests that end the session (default 5).
  --replace     overwrite a destination file that already exists.
  --ssh-host    the host name the PERSON uses to reach this machine; it is
                written into the printed tunnel command (default `<host>`).
  --dry-run     check every declaration, print what would be served and
                written (names and paths only), bind nothing, write nothing.

The session is ONE SUBMISSION. The form carries one password field per
declared name and a field for the code; the first POST that carries the right
code, every declared name and nothing else writes every file and ends the
session. It also ends after --timeout seconds, after --max-refused refused
requests, or on SIGTERM, SIGINT or SIGHUP, writing nothing.

stdout, in order (every line flushed as it is printed):
  SAFE-BOX READY port=<port> path=/<token>/ code=<XXXX-XXXX> expires=<UTC ISO> names=<a,b>
  tunnel: ssh -N -L <port>:127.0.0.1:<port> <ssh-host>
  open: http://127.0.0.1:<port>/<token>/
  request: <METHOD> <status>[ (refused <n> of <max>)]       one per request
  <name>: written (<bytes> bytes) <path>                     one per name, at the end
  <name>: NOT written (<reason>) <path>
  SAFE-BOX END <complete|timeout|too-many-refused|signal> written=<k>/<n>
With --dry-run: a `SAFE-BOX DRY-RUN` line, a `would serve:` line and one
`would write:` line per name, then exit.

Exit codes: 0 every declared secret written; 1 the session ended with at least
one not written; 2 refused at startup (a declaration is invalid, outside the
allowed roots, or names an existing file without --replace), nothing served or
written; 3 the port cannot be bound.

LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole,
and safe_box.test.py runs a broken copy for each that must fail its named check:

  * THE LISTENER IS 127.0.0.1, NEVER A WILDCARD (BIND). The person reaches it
    through an SSH local forward (`ssh -L`), which authenticates them and
    encrypts the traffic, so the form needs no TLS of its own. Bind 0.0.0.0 and
    the form, its code prompt and the secrets in transit are plain HTTP on every
    interface of the host.

  * THE URL PATH IS 192 RANDOM BITS AND A POST ALSO NEEDS THE CODE. Any local
    user of the host can connect to a 127.0.0.1 port; the path is what they
    cannot guess, and the code (typed, never in a URL, so never in browser
    history) is what a leaked URL alone does not give. Both are compared in
    constant time. A request with a wrong path, code or Host header is a 404
    and counts toward --max-refused, so probing ends the session.

  * A SECRET TRAVELS ONLY IN THE POST BODY AND ENDS ONLY IN ITS FILE. Not in a
    URL, a log line, stdout or stderr, a process argument, the environment or a
    temp file outside the destination directory. The HTTP server's default
    request log is silenced (it prints every URL path, the token included);
    each request is reported as method and status only. Core dumps are
    disabled for the process.

  * EVERY DESTINATION IS FIXED AT STARTUP AND CONFINED. A declared path is
    resolved through every symlink (realpath) and must then lie under the fleet
    secrets directory (fleetlib.paths.secrets_dir()) or under an existing agent
    home's personal secrets directory, <agents_root>/<agent>/secrets/personal/
    (the /agent default layout), where an agent home is a child of the agents
    root holding the agent's Claude Code config directory, <agent>/.claude; a
    knowledge store or the claims directory there is no agent's home, and a
    secrets/personal/ under it is refused. A path with a `..` component is
    refused even when it would resolve inside a root: it is never what a
    caller meant to type. The form cannot add or change a path, and a field
    for an undeclared name refuses the whole submission.

  * A FILE IS WRITTEN ATOMICALLY, 0600 FROM ITS CREATION. A temp file in the
    destination directory is created with os.open(..., 0600), written, fsynced
    and then renamed (--replace) or hard-linked (otherwise) into place, so a
    reader never sees a partial file and the value is never on disk under a
    looser mode. Without --replace the link refuses an existing file even when
    it appears after startup; the startup check is what refuses it before the
    person types anything. Missing parent directories are created 0700.

What it does not defend against: a process running as the same user or as
root on the host, which can read the destination files themselves; and the
person's own browser and machine. Its stdout holds the URL and the code, so
whoever reads it can SUBMIT values for the declared names, never read one.
"""

import argparse
import datetime
import hmac
import html
import os
import re
import resource
import secrets
import signal
import socketserver
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(os.path.realpath(__file__)).parents[3] / "lib"))
from fleetlib import FleetError, paths  # noqa: E402 - path set just above

BIND = "127.0.0.1"
FILE_MODE = 0o600
DIR_MODE = 0o700
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_BODY = 1 << 20
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
PERSONAL = ("secrets", "personal")
HEADERS = (
    ("Cache-Control", "no-store"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'; frame-ancestors 'none'"),
)
_PRINT = threading.Lock()


class Refused(Exception):
    """A declaration cannot be served; nothing was served or written (exit 2)."""


def say(line):
    """One stdout line, flushed. A reader that went away (the SSH link dropped)
    never stops the session: the files are still written and reported."""
    with _PRINT:
        try:
            print(line, flush=True)
        except OSError:
            pass


# ------------------------------------------------------------ destinations

class Entry:
    def __init__(self, name, path):
        self.name, self.path = name, path


def within(path, root):
    return path != root and os.path.commonpath([path, root]) == root


def roots():
    """The fleet secrets directory and the agents root, each as a realpath, or
    None with the reason it does not resolve."""
    why = []
    try:
        fleet = os.path.realpath(paths.secrets_dir())
    except FleetError as exc:
        fleet = None
        why.append(f"the fleet secrets directory does not resolve: {exc}")
    try:
        agents = os.path.realpath(os.path.expanduser(paths.host()["agents_root"]))
    except FleetError as exc:
        agents = None
        why.append(f"no agent home resolves: {exc}")
    return fleet, agents, why


def plan(pairs, replace):
    """Every NAME=PATH as an Entry whose path is resolved and confined, or Refused."""
    fleet, agents, why = roots()
    entries, names, dests = [], set(), set()
    for pair in pairs:
        name, sep, raw = pair.partition("=")
        if not sep or not raw or not NAME_RE.fullmatch(name):
            raise Refused(f"{pair!r} is not NAME=PATH with NAME matching {NAME_RE.pattern}")
        if name in names:
            raise Refused(f"{name}: declared twice")
        names.add(name)
        if ".." in raw.split("/"):
            raise Refused(f"{name}: the path has a '..' component")
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            if fleet is None:
                raise Refused(f"{name}: a relative path resolves against the fleet secrets directory, "
                              f"and {why[0]}")
            path = os.path.join(fleet, path)
        try:
            dest = os.path.realpath(path)
        except ValueError as exc:
            raise Refused(f"{name}: {exc}") from None
        allowed = fleet is not None and within(dest, fleet)
        if not allowed and agents is not None and within(dest, agents):
            # An agent home is the agents root's child that holds the agent's
            # Claude Code config directory, <home>/.claude, which the install
            # creates (/agent's home layout). The agents root holds other
            # directories - a knowledge store, the claims directory - and a
            # secrets/personal/ under one of them belongs to no agent.
            parts = os.path.relpath(dest, agents).split(os.sep)
            allowed = (len(parts) > 3 and tuple(parts[1:3]) == PERSONAL
                       and os.path.isdir(os.path.join(agents, parts[0], ".claude")))
        if not allowed:
            raise Refused(f"{name}: {dest} is outside the fleet secrets directory and every agent "
                          f"home's secrets/personal directory" + (f" ({'; '.join(why)})" if why else ""))
        if os.path.lexists(dest):
            if os.path.isdir(dest):
                raise Refused(f"{name}: {dest} is a directory")
            if not replace:
                raise Refused(f"{name}: {dest} exists; pass --replace to overwrite it")
        if dest in dests:
            raise Refused(f"{name}: {dest} is declared for another name too")
        dests.add(dest)
        entries.append(Entry(name, dest))
    return entries


def make_dirs(parent):
    """Create every missing directory down to `parent`, each mode 0700."""
    missing, p = [], parent
    while not os.path.lexists(p):
        missing.append(p)
        p = os.path.dirname(p)
    for d in reversed(missing):
        os.mkdir(d, DIR_MODE)
        os.chmod(d, DIR_MODE)


def write_one(entry, data, replace):
    """Write `data` to entry.path atomically, mode 0600 from creation."""
    parent = os.path.dirname(entry.path)
    make_dirs(parent)
    if os.path.realpath(parent) != parent:
        raise OSError(f"{parent} no longer resolves to itself")
    tmp = os.path.join(parent, f".{os.path.basename(entry.path)}.safe-box-{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, FILE_MODE)
    try:
        try:
            os.fchmod(fd, FILE_MODE)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        if replace:
            os.replace(tmp, entry.path)
        else:
            os.link(tmp, entry.path)  # EEXIST when the file appeared: never overwrites
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


# ----------------------------------------------------------------- session

class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer without its reverse DNS lookup. HTTPServer.server_bind asks
    socket.getfqdn() for a name for the bound address, a name nothing here uses, and
    on a host whose resolver is slow to answer that lookup holds the READY line back
    for as long as the resolver takes - longer than a person's wait or a test's:
    getfqdn('127.0.0.1') took 35 s on GitHub's macos-latest runner (measured
    2026-11-07)."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = BIND, self.server_address[1]


class Box:
    """The session: the expected path and code, the refusal count, and its end."""

    def __init__(self, entries, args):
        self.entries = entries
        self.names = [e.name for e in entries]
        self.replace = args.replace
        self.max_refused = args.max_refused
        self.path = f"/{secrets.token_urlsafe(24)}/"
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self.code, self.shown_code = raw, f"{raw[:4]}-{raw[4:]}"
        self.expires = (datetime.datetime.now(datetime.timezone.utc)
                        + datetime.timedelta(seconds=args.timeout)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.replied = threading.Event()
        self.reason = None
        self.refusals = 0
        self.results = []

    def end(self, reason):
        with self.lock:
            if self.reason is None:
                self.reason = reason
        self.done.set()

    def refuse(self):
        with self.lock:
            self.refusals += 1
            return self.refusals

    def path_ok(self, path):
        path = path if path.endswith("/") else path + "/"
        return hmac.compare_digest(path.encode(), self.path.encode())

    def code_ok(self, given):
        given = re.sub(r"[\s-]", "", given).upper()
        return hmac.compare_digest(given.encode(), self.code.encode())

    def write_all(self, values):
        """Write every declared value once; None when the session has already ended."""
        with self.lock:
            if self.reason is not None:
                return None
            for e in self.entries:
                data = values[e.name].encode("utf-8")
                try:
                    write_one(e, data, self.replace)
                    self.results.append((e, len(data), None))
                except OSError as exc:
                    self.results.append((e, len(data), exc.strerror or str(exc)))
            self.reason = "complete"
            return self.results


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<link rel="icon" href="data:,">
<title>safe-box</title>
<style>
body{font-family:system-ui,sans-serif;max-width:36rem;margin:2rem auto;padding:0 1rem;line-height:1.4}
label{display:block;margin:1rem 0 .25rem;font-weight:600}
input{width:100%;box-sizing:border-box;padding:.5rem;font-family:monospace}
button{margin-top:1.5rem;padding:.5rem 1.5rem}
p{color:#444}
</style></head><body>
@BODY@
</body></html>
"""


def form_page(box):
    fields = "\n".join(
        f'<label for="s{i}">{html.escape(e.name)}</label>\n'
        f'<input id="s{i}" name="s-{html.escape(e.name)}" type="password" required '
        f'autocomplete="new-password" spellcheck="false">'
        for i, e in enumerate(box.entries))
    body = (f"<h1>safe-box</h1>\n<p>Each value is written to its file on the host and is never shown "
            f"again. One submission writes them all and ends the session; it closes by itself at "
            f"{box.expires} (UTC).</p>\n"
            f'<form method="post" action="" autocomplete="off" accept-charset="utf-8">\n'
            f'<label for="code">Code from the session</label>\n'
            f'<input id="code" name="code" type="text" required autocomplete="off" '
            f'autocapitalize="characters" spellcheck="false">\n{fields}\n'
            f'<button type="submit">Write</button>\n</form>')
    return PAGE.replace("@BODY@", body)


def result_page(results):
    rows = "\n".join(
        f"<li>{html.escape(e.name)}: " + ("written" if err is None else "NOT written") + "</li>"
        for e, _, err in results)
    return PAGE.replace("@BODY@", f"<h1>safe-box</h1>\n<ul>\n{rows}\n</ul>\n"
                                  f"<p>The session has ended. Close this page and the tunnel.</p>")


class Handler(BaseHTTPRequestHandler):
    server_version = "safe-box"
    sys_version = ""
    timeout = 15  # a connection that sends nothing is dropped, never held open

    def log_message(self, format, *args):  # noqa: A002 - the base class's signature
        """Silenced: the default writes every request line, URL path included, to stderr."""

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._refuse
        raise AttributeError(name)

    def _reply(self, status, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        for key, value in HEADERS:
            self.send_header(key, value)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _refuse(self, status=404, body="Not found.\n"):
        box = self.server.box
        n = box.refuse()
        try:
            self._reply(status, body)
        finally:
            say(f"request: {self.command} {status} (refused {n} of {box.max_refused})")
            if n >= box.max_refused:
                box.end("too-many-refused")

    def _addressed(self):
        """The right Host (a loopback name) and the right path."""
        host = self.headers.get("Host", "").strip().lower()
        hostname = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
        path = urllib.parse.urlsplit(self.path).path
        return hostname in LOCAL_HOSTS and self.server.box.path_ok(path)

    def do_GET(self):
        box = self.server.box
        if box.reason is not None or not self._addressed():
            return self._refuse()
        self._reply(200, form_page(box), "text/html; charset=utf-8")
        say("request: GET 200")

    def do_POST(self):
        box = self.server.box
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._refuse(411, "Length required.\n")
        if not 0 <= length <= MAX_BODY:
            return self._refuse(413, "Too large.\n")
        # Read the body before any refusal: closing a socket with unread data in
        # it resets the connection, and the client then never sees the 404.
        body = self.rfile.read(length)
        if box.reason is not None or not self._addressed():
            return self._refuse()
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            return self._refuse(415, "Not a form submission.\n")
        try:
            fields = urllib.parse.parse_qsl(body.decode("ascii"), keep_blank_values=True, strict_parsing=True,
                                            encoding="utf-8", errors="strict",
                                            max_num_fields=len(box.entries) + 16)
        except (UnicodeError, ValueError):
            return self._refuse(400, "Malformed form.\n")
        given = {}
        for key, value in fields:
            if key in given:
                return self._refuse(400, "A field is repeated; nothing was written.\n")
            given[key] = value
        if not box.code_ok(given.pop("code", "")):
            return self._refuse()
        values = {}
        for key, value in given.items():
            if not (key.startswith("s-") and key[2:] in box.names):
                return self._refuse(400, "A field is not declared; nothing was written.\n")
            values[key[2:]] = value
        if any(not values.get(n) for n in box.names):
            return self._refuse(400, "Every field is required; nothing was written.\n")
        results = box.write_all(values)
        if results is None:
            return self._refuse()
        status = 200 if all(err is None for _, _, err in results) else 500
        try:
            self._reply(status, result_page(results), "text/html; charset=utf-8")
        finally:
            say(f"request: POST {status}")
            box.replied.set()
            box.end("complete")


# -------------------------------------------------------------------- main

def parse(argv):
    ap = argparse.ArgumentParser(prog="safe_box.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("pairs", nargs="+", metavar="NAME=PATH")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--max-refused", type=int, default=5)
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--ssh-host", default="<host>")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not 1 <= args.timeout <= 3600:
        ap.error("--timeout is 1 to 3600 seconds")
    if not 0 <= args.port <= 65535:
        ap.error("--port is 0 to 65535")
    if not 1 <= args.max_refused <= 100:
        ap.error("--max-refused is 1 to 100")
    return args


def main(argv=None):
    args = parse(argv)
    try:
        entries = plan(args.pairs, args.replace)
    except Refused as exc:
        print(f"safe-box: refused, nothing served or written: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        say("SAFE-BOX DRY-RUN nothing is served and nothing is written")
        say(f"would serve: one form on {BIND} port {args.port or 'a free port'} for {args.timeout:g} s, "
            f"one submission, at most {args.max_refused} refused requests")
        for e in entries:
            how = "replaces the existing file" if os.path.lexists(e.path) else "new file"
            say(f"would write: {e.name} -> {e.path} ({how}, mode 600, missing directories 700)")
        return 0
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass
    box = Box(entries, args)
    try:
        server = Server((BIND, args.port), Handler)
    except OSError as exc:
        print(f"safe-box: cannot listen on {BIND}:{args.port}: {exc.strerror or exc}", file=sys.stderr)
        return 3
    server.daemon_threads = True
    server.box = box
    port = server.server_address[1]
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: box.end("signal"))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    say(f"SAFE-BOX READY port={port} path={box.path} code={box.shown_code} expires={box.expires} "
        f"names={','.join(box.names)}")
    say(f"tunnel: ssh -N -L {port}:{BIND}:{port} {args.ssh_host}")
    say(f"open: http://{BIND}:{port}{box.path}")
    box.done.wait(args.timeout)
    box.end("timeout")
    if box.reason == "complete":
        box.replied.wait(5)
    server.shutdown()
    server.server_close()
    for e, size, err in box.results:
        say(f"{e.name}: written ({size} bytes) {e.path}" if err is None
            else f"{e.name}: NOT written ({err}) {e.path}")
    written = sum(1 for _, _, err in box.results if err is None)
    say(f"SAFE-BOX END {box.reason} written={written}/{len(entries)}")
    return 0 if box.reason == "complete" and written == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())
