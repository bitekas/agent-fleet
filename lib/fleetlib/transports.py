"""The chat-transport registry: every `.claude/skills/*/transport.json` in a fleet tree.

The skill directory holding a transport.json is that transport's skill. Each
descriptor is validated against schema 1 (documented by the `chat-transport`
skill); one invalid descriptor refuses the whole registry with DescriptorError
(exit 3) naming the file and the key, because a registry that skipped it would
quietly drop that transport from every daemon and every origin check.

Each returned descriptor is the file's content plus two derived keys:
`skill` (the directory name) and `skill_dir` (its absolute path).

Which tree is read, first match wins:
  1. the `skills_dir` argument, when a caller passes one;
  2. $FLEET_TRANSPORTS_DIR - TEST-ONLY. It exists so that a test which runs a
     fleet command in a subprocess can point the registry at
     tests/fixtures/transports/, whose working descriptor carries exactly the
     Slack values of the chat-transport contract. Nothing in production sets it,
     and a host where it is set reads transports from that directory instead of
     its own fleet tree;
  3. `<fleet root>/.claude/skills`, the tree this library was imported from.
"""

import json
import os
import re
from pathlib import Path

from . import DescriptorError, Refused
from .paths import fleet_root

STATUSES = ("working", "placeholder")
KINDS = ("channel", "dm", "thread")
ID_KEYS = ("user", "conversation", "message")
TOP_KEYS = ("schema", "name", "status", "line_prefix", "kinds", "ids", "watch")
WATCH_KEYS = ("script", "job", "config_env", "follow_include")

_NAME = re.compile(r"[a-z][a-z0-9-]*")
# Job names no transport may take: under launchd a job's label is
# <prefix>.<job>.<agent>, and these two are the session's and the stall
# watchdog's (fleetlib.services reads this tuple).
RESERVED_JOBS = ("session", "stall-watchdog")
_PREFIX = re.compile(r"[A-Z][A-Z0-9_]*")
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def registry_dir(skills_dir=None):
    """The directory whose `*/transport.json` files form the registry."""
    if skills_dir is not None:
        return Path(skills_dir)
    env = os.environ.get("FLEET_TRANSPORTS_DIR")
    if env:
        return Path(env)
    return fleet_root() / ".claude" / "skills"


def _fail(path, key, what):
    raise DescriptorError(f"{path}: `{key}` {what}", key=key)


def _keys(path, obj, allowed, where):
    if not isinstance(obj, dict):
        _fail(path, where, "is not an object")
    for k in obj:
        if k not in allowed:
            _fail(path, f"{where}.{k}" if where else k, "is not a schema-1 key")
    for k in allowed:
        if k not in obj:
            _fail(path, f"{where}.{k}" if where else k, "is missing")


def _regex(path, key, value, anchored):
    if not isinstance(value, str) or not value:
        _fail(path, key, "is not a non-empty string")
    try:
        re.compile(value)
    except re.error as exc:
        _fail(path, key, f"does not compile: {exc}")
    if anchored and not (value.startswith("^") and value.endswith("$")):
        _fail(path, key, "is not anchored with ^...$ (a partial match would accept a malformed id)")


def validate(d, path="transport.json"):
    """Raise DescriptorError unless `d` is a schema-1 transport descriptor."""
    _keys(path, d, TOP_KEYS, "")
    if type(d["schema"]) is not int or d["schema"] != 1:
        _fail(path, "schema", "is not 1")
    if not isinstance(d["name"], str) or not _NAME.fullmatch(d["name"]):
        _fail(path, "name", "is not a lowercase transport name")
    if d["status"] not in STATUSES:
        _fail(path, "status", f"is not one of {', '.join(STATUSES)}")
    if not isinstance(d["line_prefix"], str) or not _PREFIX.fullmatch(d["line_prefix"]):
        _fail(path, "line_prefix", "is not an uppercase line prefix")
    kinds = d["kinds"]
    if (not isinstance(kinds, list) or not kinds or len(set(map(str, kinds))) != len(kinds)
            or any(k not in KINDS for k in kinds)):
        _fail(path, "kinds", f"is not a non-empty list of distinct kinds from {', '.join(KINDS)}")
    _keys(path, d["ids"], ID_KEYS, "ids")
    for k in ID_KEYS:
        _regex(path, f"ids.{k}", d["ids"][k], anchored=True)
    w = d["watch"]
    _keys(path, w, WATCH_KEYS, "watch")
    if not isinstance(w["script"], str) or not w["script"] or "/" in w["script"]:
        _fail(path, "watch.script", "is not a file name in the transport's skill directory")
    if not isinstance(w["job"], str) or not _NAME.fullmatch(w["job"]):
        _fail(path, "watch.job", "is not a lowercase job name")
    if w["job"] in RESERVED_JOBS:
        _fail(path, "watch.job", f"is {w['job']!r}, which is reserved: under launchd it is the {w['job']} "
                                 "unit's label")
    if not isinstance(w["config_env"], str) or not _ENV.fullmatch(w["config_env"]):
        _fail(path, "watch.config_env", "is not an environment variable name")
    _regex(path, "watch.follow_include", w["follow_include"], anchored=False)


def all(skills_dir=None):  # noqa: A001 - the design names the call transports.all()
    """Every descriptor, validated, sorted by name."""
    base = registry_dir(skills_dir)
    out = {}
    for path in sorted(base.glob("*/transport.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DescriptorError(f"{path}: cannot be read: {exc.strerror}") from None
        except ValueError as exc:
            raise DescriptorError(f"{path}: not valid JSON: {exc}") from None
        validate(d, path)
        if d["name"] in out:
            raise DescriptorError(
                f"{path}: transport name `{d['name']}` is also declared by "
                f"{out[d['name']]['skill_dir']}/transport.json; a name is unique in the fleet tree",
                key="name")
        skill_dir = path.parent
        out[d["name"]] = {**d, "skill": skill_dir.name, "skill_dir": str(skill_dir)}
    return [out[k] for k in sorted(out)]


def get(name, skills_dir=None):
    """The descriptor named `name`; Refused (exit 2) when there is none."""
    found = all(skills_dir)
    for d in found:
        if d["name"] == name:
            return d
    known = ", ".join(d["name"] for d in found) or "none"
    raise Refused(f"no transport named {name!r} (known: {known})")


def working(skills_dir=None):
    """The descriptors whose status is `working` - the ones daemons and origins use."""
    return [d for d in all(skills_dir) if d["status"] == "working"]
