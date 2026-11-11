"""The install manifest `<install root>/.claude/fleet.json`, schema 1.

load(install_root) parses it, strips every `_`-prefixed key at any depth (JSON
has no comments, so `_comment` keys are documentation), and validates it:
an unknown key, a wrong type, a missing required key or a broken invariant is a
ManifestError (exit 2) whose `key` names the offending dotted key.

ONE PLACEHOLDER RULE, so a copy of the template that was never filled in is
refused rather than printed: a string value that is one `<...>` as a whole,
with a space inside and no `@` (`<Your Name>`), is the template's, never an
install's, and is refused naming its key. templates/fleet.example.json writes
every value an install must replace that way. Install data keeps its forms: a
placeholder inside a doc path (`docs/checklists/<feature-slug>.md`) or a
one-word one (`<version>`) is filled in when it is read, and a chat mention
(`<@ada>`) or an address (`<ada@example.com>`) is a value.

settings(m) is the view skills read: house rules, conventions and secrets with
the fleet defaults applied. `fleet settings` prints it, after check_paths(m,
root) has refused a convention or a deny list that names a file the install
does not have.

The key tuples below are the ONE enumeration of schema 1. Validation, the
defaults, schema_keys() and the tests that hold templates/fleet.example.json
and CONVENTIONS.md to the schema all read them; a key added here and nowhere
else reds those tests.
"""

import copy
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import EnvironmentFault, ManifestError
from . import transports as _transports

TOP_KEYS = ("schema", "fleet", "skills", "transports", "conventions",
            "house_rules", "secrets", "upstream")
REQUIRED = ("schema", "fleet", "skills", "transports")
FLEET_KEYS = ("repo", "min_tag")
TRANSPORT_KEYS = ("enabled", "default")
CONVENTION_KEYS = ("definition_of_done", "feature_checklist", "branch_naming",
                   "workspace", "release", "environments", "people_notes")
CONVENTION_FORMS = ("skill", "doc")
HOUSE_KEYS = ("questions_per_message", "blocker_chase", "state_the_fact", "times",
              "ascii_skill_prose")
BLOCKER_KEYS = ("every_minutes", "tz", "days", "start", "end")
TIMES_KEYS = ("cities",)
CITY_KEYS = ("name", "tz")
SECRETS_KEYS = ("legacy_env", "default_dir")
UPSTREAM_KEYS = ("identity", "deny_list", "outside_pr_reviewer")
IDENTITY_KEYS = ("name", "email")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CHAT_TRANSPORT_SKILL = "chat-transport"

# The fleet defaults. The fleet ships NO development convention: an absent or
# null convention means the install has none, and the reading skill skips that
# step and says so.
DEFAULT_CONVENTIONS = {k: None for k in CONVENTION_KEYS}
DEFAULT_HOUSE_RULES = {
    "questions_per_message": 1,
    "blocker_chase": {"every_minutes": 60, "tz": "UTC",
                      "days": ["mon", "tue", "wed", "thu", "fri"],
                      "start": "09:00", "end": "18:00"},
    "state_the_fact": True,
    "times": {"cities": [{"name": "UTC", "tz": "UTC"}]},
    "ascii_skill_prose": True,
}
DEFAULT_SECRETS = {"legacy_env": None, "default_dir": "~/.fleet-secrets"}

_SKILL = re.compile(r"[a-z0-9][a-z0-9-]*")
_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HHMM = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_PLACEHOLDER = re.compile(r"<[^<>@]*\s[^<>@]*>")  # fullmatch: the template's placeholder form


def schema_keys():
    """Every dotted key of schema 1; `[]` marks the fields of a list's items."""
    keys = list(TOP_KEYS)
    keys += [f"fleet.{k}" for k in FLEET_KEYS]
    keys += [f"transports.{k}" for k in TRANSPORT_KEYS]
    keys += [f"conventions.{k}" for k in CONVENTION_KEYS]
    keys += [f"house_rules.{k}" for k in HOUSE_KEYS]
    keys += [f"house_rules.blocker_chase.{k}" for k in BLOCKER_KEYS]
    keys += [f"house_rules.times.{k}" for k in TIMES_KEYS]
    keys += [f"house_rules.times.cities[].{k}" for k in CITY_KEYS]
    keys += [f"secrets.{k}" for k in SECRETS_KEYS]
    keys += [f"upstream.{k}" for k in UPSTREAM_KEYS]
    keys += [f"upstream.identity.{k}" for k in IDENTITY_KEYS]
    return keys


def strip_comments(v):
    """`v` without any `_`-prefixed key, at any depth."""
    if isinstance(v, dict):
        return {k: strip_comments(x) for k, x in v.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(v, list):
        return [strip_comments(x) for x in v]
    return v


def _merge(default, given):
    """`given` over `default`, recursing into objects; a list replaces wholesale."""
    if isinstance(default, dict) and isinstance(given, dict):
        out = copy.deepcopy(default)
        for k, v in given.items():
            out[k] = _merge(default[k], v) if k in default else copy.deepcopy(v)
        return out
    return copy.deepcopy(given)


class _Checker:
    def __init__(self, source):
        self.source = source

    def fail(self, key, what):
        raise ManifestError(f"{self.source}: `{key}` {what}", key=key)

    def obj(self, v, key, allowed, required=()):
        if not isinstance(v, dict):
            self.fail(key, "is not an object")
        for k in v:
            if k not in allowed:
                self.fail(f"{key}.{k}" if key else k, "is not a schema-1 key")
        for k in required:
            if k not in v:
                self.fail(f"{key}.{k}" if key else k, "is missing")

    def string(self, v, key):
        if not isinstance(v, str) or not v:
            self.fail(key, "is not a non-empty string")

    def integer(self, v, key):
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            self.fail(key, "is not a positive integer")

    def boolean(self, v, key):
        if not isinstance(v, bool):
            self.fail(key, "is not true or false")

    def names(self, v, key, pattern=None):
        if not isinstance(v, list) or not v:
            self.fail(key, "is not a non-empty list")
        for x in v:
            if not isinstance(x, str) or (pattern and not pattern.fullmatch(x)):
                self.fail(key, f"holds {x!r}, which is not a valid name")
        if len(set(v)) != len(v):
            self.fail(key, "holds a name twice")

    def no_placeholder(self, v, key=""):
        """Refuse the first string, in document order, in the template's placeholder form."""
        items = enumerate(v) if isinstance(v, list) else v.items() if isinstance(v, dict) else ()
        for k, x in items:
            sub = f"{key}[{k}]" if isinstance(v, list) else (f"{key}.{k}" if key else str(k))
            if isinstance(x, str) and _PLACEHOLDER.fullmatch(x):
                self.fail(sub, f"still holds the template's placeholder {x!r}; replace it with this install's value")
            self.no_placeholder(x, sub)

    def zone(self, v, key):
        self.string(v, key)
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            self.fail(key, f"is {v!r}, which is not an IANA time zone that loads on this host")


def validate(m, *, skills_dir=None, source="install manifest"):
    """Raise ManifestError unless `m` (comments stripped) is a valid schema-1 manifest.

    `skills_dir` selects the transport registry the transport invariants are
    checked against (see transports.registry_dir).
    """
    c = _Checker(source)
    # First: a placeholder in a typed field (`"min_tag": "<tag>"`) would otherwise
    # be refused as a malformed value, which hides that the file was never filled in.
    c.no_placeholder(m)
    c.obj(m, "", TOP_KEYS, REQUIRED)
    if type(m["schema"]) is not int or m["schema"] != 1:
        c.fail("schema", f"is {m['schema']!r}; this fleet reads schema 1")

    c.obj(m["fleet"], "fleet", FLEET_KEYS, FLEET_KEYS)
    c.string(m["fleet"]["repo"], "fleet.repo")
    if not isinstance(m["fleet"]["min_tag"], str) or not _TAG.fullmatch(m["fleet"]["min_tag"]):
        c.fail("fleet.min_tag", "is not a vMAJOR.MINOR.PATCH tag")

    c.names(m["skills"], "skills", _SKILL)

    t = m["transports"]
    c.obj(t, "transports", TRANSPORT_KEYS, TRANSPORT_KEYS)
    c.names(t["enabled"], "transports.enabled", _SKILL)
    c.string(t["default"], "transports.default")

    conv = m.get("conventions", {})
    c.obj(conv, "conventions", CONVENTION_KEYS)
    for k, v in conv.items():
        key = f"conventions.{k}"
        if v is None:
            continue
        c.obj(v, key, (*CONVENTION_FORMS, "section"))
        forms = [f for f in CONVENTION_FORMS if f in v]
        if len(forms) != 1:
            c.fail(key, 'is not exactly one of {"skill": ...} or {"doc": ...}')
        c.string(v[forms[0]], f"{key}.{forms[0]}")
        if "section" in v and not (isinstance(v["section"], (str, int))
                                   and not isinstance(v["section"], bool) and v["section"] != ""):
            c.fail(f"{key}.section", "is not a heading or a number")

    if not isinstance(m.get("house_rules", {}), dict):
        c.fail("house_rules", "is not an object")
    h = _merge(DEFAULT_HOUSE_RULES, m.get("house_rules", {}))
    c.obj(h, "house_rules", HOUSE_KEYS)
    c.integer(h["questions_per_message"], "house_rules.questions_per_message")
    b = h["blocker_chase"]
    c.obj(b, "house_rules.blocker_chase", BLOCKER_KEYS)
    c.integer(b["every_minutes"], "house_rules.blocker_chase.every_minutes")
    if 1440 % b["every_minutes"]:
        c.fail("house_rules.blocker_chase.every_minutes",
               f"is {b['every_minutes']}, which does not divide 1440 (a day in minutes)")
    c.zone(b["tz"], "house_rules.blocker_chase.tz")
    days = b["days"]
    if (not isinstance(days, list) or not days or len(set(map(str, days))) != len(days)
            or any(d not in DAYS for d in days)):
        c.fail("house_rules.blocker_chase.days", f"is not a non-empty subset of {', '.join(DAYS)}")
    for k in ("start", "end"):
        if not isinstance(b[k], str) or not _HHMM.fullmatch(b[k]):
            c.fail(f"house_rules.blocker_chase.{k}", "is not a 24-hour HH:MM time")
    if b["start"] >= b["end"]:
        c.fail("house_rules.blocker_chase.start",
               f"is {b['start']}, not before end {b['end']}")
    c.boolean(h["state_the_fact"], "house_rules.state_the_fact")
    c.boolean(h["ascii_skill_prose"], "house_rules.ascii_skill_prose")
    c.obj(h["times"], "house_rules.times", TIMES_KEYS)
    cities = h["times"]["cities"]
    if not isinstance(cities, list) or not cities:
        c.fail("house_rules.times.cities", "is not a non-empty list")
    for i, city in enumerate(cities):
        key = f"house_rules.times.cities[{i}]"
        c.obj(city, key, CITY_KEYS, CITY_KEYS)
        c.string(city["name"], f"{key}.name")
        c.zone(city["tz"], f"{key}.tz")

    if not isinstance(m.get("secrets", {}), dict):
        c.fail("secrets", "is not an object")
    s = _merge(DEFAULT_SECRETS, m.get("secrets", {}))
    c.obj(s, "secrets", SECRETS_KEYS)
    if s["legacy_env"] is not None and not (isinstance(s["legacy_env"], str)
                                            and _ENV.fullmatch(s["legacy_env"])):
        c.fail("secrets.legacy_env", "is not null or an environment variable name")
    c.string(s["default_dir"], "secrets.default_dir")

    if "upstream" in m:
        u = m["upstream"]
        c.obj(u, "upstream", UPSTREAM_KEYS)
        if "identity" in u:
            c.obj(u["identity"], "upstream.identity", IDENTITY_KEYS, IDENTITY_KEYS)
            for k in IDENTITY_KEYS:
                c.string(u["identity"][k], f"upstream.identity.{k}")
        if "deny_list" in u and u["deny_list"] is not None:
            c.string(u["deny_list"], "upstream.deny_list")
        if "outside_pr_reviewer" in u:
            c.string(u["outside_pr_reviewer"], "upstream.outside_pr_reviewer")

    # Invariants across keys, and against the fleet tree's transport registry.
    if t["default"] not in t["enabled"]:
        c.fail("transports.default", f"is {t['default']!r}, which is not in transports.enabled")
    registry = {d["name"]: d for d in _transports.all(skills_dir)}
    where = _transports.registry_dir(skills_dir)
    for name in t["enabled"]:
        if name not in registry:
            c.fail("transports.enabled", f"names {name!r}, which no transport.json under {where} declares")
        if registry[name]["status"] != "working":
            c.fail("transports.enabled",
                   f"names {name!r}, a {registry[name]['status']} transport; only working ones can be enabled")
    needed = [CHAT_TRANSPORT_SKILL] + [registry[n]["skill"] for n in t["enabled"]]
    missing = [n for n in needed if n not in m["skills"]]
    if missing:
        c.fail("skills", f"lacks {', '.join(missing)} (chat-transport and every enabled transport's skill)")


_READ_TIME = re.compile(r"<[^<>]*>")  # search: a doc path that is filled in when it is read


def check_paths(m, install_root):
    """Raise ManifestError naming the key when a value of `m` (a manifest load()
    returned) points at a file the install at `install_root` does not have: a
    convention skill without `<install root>/.claude/skills/<name>/SKILL.md`, a
    convention doc, or `upstream.deny_list`. A doc path holding a read-time
    placeholder (`<feature-slug>`) names no file until it is read, so it is not
    followed. A relative path resolves against the install root, as the leak gate
    resolves the deny list; `~` expands.

    One stat per value. It is NOT part of load(): load() runs on every daemon
    refresh, link and claim, where a document moved in the install must not stop
    the fleet. `fleet settings` runs it, which is where SETUP checks a manifest and
    how an agent reads a convention.
    """
    root = Path(install_root)
    c = _Checker(f"install manifest {root / '.claude' / 'fleet.json'}")

    def resolve(p):
        p = Path(p).expanduser()
        return p if p.is_absolute() else root / p

    for k, v in m.get("conventions", {}).items():
        if v is None:
            continue
        if "skill" in v:
            p = root / ".claude" / "skills" / v["skill"] / "SKILL.md"
            if not p.is_file():
                c.fail(f"conventions.{k}.skill", f"names skill {v['skill']!r}, but {p} does not exist")
        elif not _READ_TIME.search(v["doc"]) and not resolve(v["doc"]).is_file():
            c.fail(f"conventions.{k}.doc", f"names {v['doc']!r}, but {resolve(v['doc'])} does not exist")
    deny = m.get("upstream", {}).get("deny_list")
    if deny is not None and not resolve(deny).is_file():
        c.fail("upstream.deny_list", f"names {deny!r}, but {resolve(deny)} does not exist, and the "
                                     f"commit gate stops at exit 3 on a list it cannot read; write "
                                     f"the list there, or set the key to null to state the install "
                                     f"has no private values")


def load(install_root, *, skills_dir=None):
    """The validated manifest of the install at `install_root`, comments stripped.

    A missing or unreadable file is EnvironmentFault (exit 3); invalid JSON or a
    schema violation is ManifestError (exit 2) naming the key.
    """
    path = Path(install_root) / ".claude" / "fleet.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise EnvironmentFault(f"no install manifest at {path}", variable="FLEET_CONTEXT_ROOT") from None
    except OSError as exc:
        raise EnvironmentFault(f"the install manifest cannot be read ({path}): {exc.strerror}",
                               variable="FLEET_CONTEXT_ROOT") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"install manifest {path} is not valid JSON: {exc}") from None
    m = strip_comments(data)
    validate(m, skills_dir=skills_dir, source=f"install manifest {path}")
    return m


def settings(m):
    """The resolved settings of a manifest returned by load(): every key of the
    manifest, with every key of CONVENTION_KEYS present (absent = None), and
    house_rules and secrets deep-merged over the fleet defaults (a list replaces
    the default list wholesale).

    `upstream` has NO defaults and stays absent when the manifest omits it: a
    defaulted `deny_list` of null would read as the install's statement that it
    has no private values, which only the install may make.
    """
    out = {
        "schema": m["schema"],
        "fleet": copy.deepcopy(m["fleet"]),
        "skills": list(m["skills"]),
        "transports": copy.deepcopy(m["transports"]),
        "conventions": {**DEFAULT_CONVENTIONS, **copy.deepcopy(m.get("conventions", {}))},
        "house_rules": _merge(DEFAULT_HOUSE_RULES, m.get("house_rules", {})),
        "secrets": _merge(DEFAULT_SECRETS, m.get("secrets", {})),
    }
    if "upstream" in m:
        out["upstream"] = copy.deepcopy(m["upstream"])
    return out
