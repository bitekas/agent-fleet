"""Where things are: host settings, the install root, a skill's install context.

The fleet tree holds COMMON files only. Everything an install fills in - a
skill's CONTEXT.md, config.json, override/, temporary/ and install state - lives
in the INSTALL ROOT, the directory holding the install manifest
`.claude/fleet.json`, under `.claude/skills/<skill>/`.
"""

import json
import os
import re
import stat
from pathlib import Path

from . import EnvironmentFault, Refused
from . import expand

MANIFEST = Path(".claude") / "fleet.json"
HOST_DEFAULT = Path(".config") / "agent-fleet" / "host.json"
HOST_KEYS = ("agents_root", "fleet_checkout", "claims_dir")
# An agent's name: its home directory under agents_root, and the instance part of
# every unit and label the fleet gives it.
AGENT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Optional host settings, each with its default and the rule a present value
# must meet. launchd_prefix: the reverse-DNS prefix of every launchd label the
# fleet installs, so a test install and a real one on one Mac never share a
# label. launchd_domain: the launchd domain user jobs run in, `gui` (the Aqua
# session of a logged-in user, where the keychain and a headful browser work)
# or `user` (the background domain, present without a login).
HOST_OPTIONAL = {
    "launchd_prefix": ("com.agent-fleet", re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+")),
    "launchd_domain": ("gui", re.compile(r"gui|user")),
    # The interpreter every unit and plist runs, when not the backend's default
    # (/usr/bin/python3; Homebrew's /opt/homebrew/bin/python3 on macOS). `fleet
    # install` writes it from FLEET_PYTHON, so one render after another uses it.
    "python": (None, re.compile(r"/[A-Za-z0-9._/+@-]+")),
}


def fleet_root():
    """The fleet tree this library was imported from.

    `realpath`, never `abspath`: imported through a link (a personal skill link,
    a symlinked lib/), abspath keeps the link path and its parents are not the
    fleet tree. paths.test.py imports the library through a symlink to prove it.
    """
    return Path(os.path.realpath(__file__)).parents[2]


def host_config_path():
    """Where the host settings are: $FLEET_HOST_CONFIG, else
    ~/.config/agent-fleet/host.json. An empty variable counts as unset. The path
    is returned whether or not the file exists."""
    env = os.environ.get("FLEET_HOST_CONFIG")
    return Path(env).expanduser() if env else Path.home() / HOST_DEFAULT


def host():
    """The host settings, read from host_config_path().

    Raises EnvironmentFault (exit 3) when the file is missing, unreadable or
    not schema 1.
    """
    path = host_config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise EnvironmentFault(
            f"the fleet is not installed on this host: run `fleet install` (no {path})",
            variable="FLEET_HOST_CONFIG") from None
    except OSError as exc:
        raise EnvironmentFault(f"the fleet host settings cannot be read ({path}): {exc.strerror}",
                               variable="FLEET_HOST_CONFIG") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise EnvironmentFault(f"the fleet host settings are not valid JSON ({path}): {exc}",
                               variable="FLEET_HOST_CONFIG") from None
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise EnvironmentFault(f"the fleet host settings at {path} are not schema 1",
                               variable="FLEET_HOST_CONFIG", key="schema")
    for k in HOST_KEYS:
        if not isinstance(data.get(k), str) or not data[k]:
            raise EnvironmentFault(f"the fleet host settings at {path} have no string `{k}`",
                                   variable="FLEET_HOST_CONFIG", key=k)
    for k, (_, rule) in HOST_OPTIONAL.items():
        if k in data and not (isinstance(data[k], str) and rule.fullmatch(data[k])):
            raise EnvironmentFault(f"the fleet host settings at {path} have a `{k}` that does not "
                                   f"match {rule.pattern}", variable="FLEET_HOST_CONFIG", key=k)
    return data


def changeable(path):
    """The first reason the running user can change `path`, or None.

    "Can change" is ownership and the directory chain, not access(2) on the
    path alone: an owner may chmod its own read-only file and then write it,
    and a user who owns or may write any directory above a path may rename the
    entry away and put another in its place - except in a sticky directory,
    where only an entry's owner may rename it. Both the path as written and its
    realpath are walked. Write access means this user's, groups included, so a
    file writable by a group the user is in counts. A path behind a directory
    the user cannot search is judged by the directories above it; one that
    cannot be inspected for any other reason counts as changeable.
    """
    me = os.geteuid()
    for p in dict.fromkeys((os.path.abspath(path), os.path.realpath(path))):
        cur = p
        while True:
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                st = None
            except PermissionError:
                # A directory above it is not searchable by this user, so the path
                # cannot be reached, let alone changed, but through a directory
                # above it this user may write: the walk goes on to those.
                st = False
            except OSError as e:
                return f"{cur} cannot be inspected ({e.strerror}), so it may be"
            if st:
                # Write access counts on the path itself; above it, a directory's
                # write access matters only through renaming the entry below,
                # which the parent step judges (a sticky bit included).
                if cur == p and not stat.S_ISLNK(st.st_mode) and os.access(cur, os.W_OK):
                    return f"may write {cur}"
                if st.st_uid == me:
                    return f"owns {cur}"
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            try:
                sticky = os.stat(parent).st_mode & stat.S_ISVTX
            except OSError:
                sticky = 0
            if os.access(parent, os.W_OK | os.X_OK) and not (sticky and st is not None):
                what = "create" if st is None else "replace"
                return f"may write {parent}, so it can {what} {os.path.basename(cur)} there"
            cur = parent
    return None


def tree_changeable(root):
    """The first reason the running user can change anything in the tree at
    `root`, or None: the root and every directory above it (changeable()), then
    every entry below it - a file or directory the user owns or may write, or a
    directory it may add to. A symlink's own owner cannot retarget it, so a
    link counts only through its directory. Every entry is visited (no early
    pruning of node_modules or .git: each is code or history a run reads)."""
    why = changeable(root)
    if why:
        return why
    me = os.geteuid()
    errors = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=errors.append):
        if os.access(dirpath, os.W_OK | os.X_OK):
            return f"may write {dirpath}, so it can replace what is in it"
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except OSError as e:
                return f"{p} cannot be inspected ({e.strerror}), so it may be"
            if stat.S_ISLNK(st.st_mode):
                continue
            if st.st_uid == me:
                return f"owns {p}"
            if os.access(p, os.W_OK):
                return f"may write {p}"
    if errors:
        return f"{errors[0].filename} cannot be listed ({errors[0].strerror}), so what is in it may be"
    return None


def host_option(key):
    """An optional host setting (HOST_OPTIONAL): its value in the host settings,
    else its default. With no host settings file at all, the default: such a
    host has no fleet units to name. A file that is there but broken is
    EnvironmentFault, as host() says."""
    default = HOST_OPTIONAL[key][0]
    if not host_config_path().exists():
        return default
    return host().get(key, default)


def _git_top(start):
    """The git top level holding `start`: the nearest ancestor with a `.git` entry
    (a directory, or the file a worktree or submodule carries).

    Found by walking the filesystem, not by running git: a hook exports GIT_DIR,
    and with GIT_DIR set `git rev-parse --show-toplevel` answers the directory
    it runs in, so a subdirectory of an install would read as a top level that
    holds no manifest. paths.test.py pins this with an exported GIT_DIR.
    """
    p = Path(os.path.realpath(start))
    for d in (p, *p.parents):
        if os.path.lexists(d / ".git"):
            return d
    return None


def home_project(agent_home):
    """The agent home's install root: the directory holding its single
    `*/.claude/fleet.json`. Zero or several is EnvironmentFault (exit 3)."""
    found = sorted(Path(agent_home).glob(f"*/{MANIFEST}"))
    if len(found) != 1:
        raise EnvironmentFault(f"{len(found)} install manifests under the agent home {agent_home} "
                               f"(expected exactly one */{MANIFEST})")
    return found[0].parent.parent


def install_root(cwd=None, git_top=True):
    """The directory holding the install manifest, first match wins:

      1. $FLEET_CONTEXT_ROOT. It must hold .claude/fleet.json; set without one
         is exit 3, never a fall-through to the steps below.
      2. The git top level of `cwd` (default: the working directory), when it
         holds .claude/fleet.json - an agent in an install worktree reads that
         tree's values. Skipped when `git_top` is False.
      3. The calling agent's home project: the agent home is the parent of
         $CLAUDE_CONFIG_DIR and must be a direct child of host.json's
         agents_root; home_project() of it. Zero or several manifests: exit 3.
         Without readable host settings this step cannot apply; the step-4
         message then carries the host-settings fault.
      4. Otherwise exit 3.

    `git_top=False` is for a caller whose working tree must never supply the
    manifest: the leak gate, whose working tree is the repository under scan,
    where a committed .claude/fleet.json could otherwise switch its deny half
    off. leak_gate.test.py pins that through the gate.

    Every failure is EnvironmentFault (exit 3) naming FLEET_CONTEXT_ROOT.
    """
    env = os.environ.get("FLEET_CONTEXT_ROOT")
    if env:
        root = Path(os.path.realpath(os.path.expanduser(env)))
        if not (root / MANIFEST).is_file():
            raise EnvironmentFault(
                f"FLEET_CONTEXT_ROOT={env} holds no {MANIFEST}: point it at the install root",
                variable="FLEET_CONTEXT_ROOT")
        return root

    why = []
    if git_top:
        top = _git_top(os.getcwd() if cwd is None else cwd)
        if top is not None and (top / MANIFEST).is_file():
            return top
        if top is not None:
            why.append(f"the git tree {top} holds no {MANIFEST}")
        else:
            why.append("the working directory is in no git tree" if cwd is None
                       else f"{cwd} is in no git tree")
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    h = None
    if config_dir:
        try:
            h = host()
        except EnvironmentFault as exc:
            why.append(f"the agent home cannot be checked: {exc}")
    else:
        why.append("CLAUDE_CONFIG_DIR is unset")
    if h is not None:
        agent_home = Path(os.path.realpath(os.path.expanduser(config_dir))).parent
        agents_root = Path(os.path.realpath(os.path.expanduser(h["agents_root"])))
        if agent_home.parent == agents_root:
            try:
                return home_project(agent_home)
            except EnvironmentFault as exc:
                raise EnvironmentFault(f"{exc}: set FLEET_CONTEXT_ROOT to the install root",
                                       variable="FLEET_CONTEXT_ROOT") from None
        why.append(f"the agent home {agent_home} is not a direct child of agents_root {agents_root}")
    raise EnvironmentFault(
        f"no install manifest resolves ({'; '.join(why)}): set FLEET_CONTEXT_ROOT to the install root",
        variable="FLEET_CONTEXT_ROOT")


def skill_context(skill, cwd=None):
    """`<install root>/.claude/skills/<skill>/`: where that skill's CONTEXT.md,
    config.json, override/, temporary/ and installation/.install-state.json live.
    The path is returned whether or not it exists."""
    if not isinstance(skill, str) or not skill or skill.startswith(".") or "/" in skill:
        raise Refused(f"not a skill name: {skill!r}")
    return install_root(cwd) / ".claude" / "skills" / skill


def resolve_config_path(value, config_file):
    """A path value read from a config file, as the file it names.

    The value is expanded (expand.value). A relative result resolves against the
    directory of `config_file`, never against the script's directory or the
    working directory: the config file stays where it is when the mechanism
    moves, so its relative paths keep naming the same files. That directory is
    taken through realpath before the value is joined and normalized, so a
    `..` in the value climbs the directory the file really is in, not the link
    it was reached through.
    """
    p = Path(expand.value(str(value)))
    if p.is_absolute():
        return p
    base = os.path.realpath(os.path.dirname(os.fspath(config_file)) or ".")
    return Path(os.path.normpath(os.path.join(base, p)))


def secrets_dir(cwd=None):
    """The directory holding this install's credential files:

      1. $FLEET_SECRETS_DIR;
      2. else the environment variable the manifest names in secrets.legacy_env;
      3. else the manifest's secrets.default_dir (relative to the manifest's
         directory, like any config path);
      4. else ~/.fleet-secrets.

    An empty variable counts as unset. Step 1 needs no install; steps 2-4 read
    the install manifest, so a failure to resolve it raises as install_root does.
    No install's variable name is written here: the manifest names it.
    """
    env = os.environ.get("FLEET_SECRETS_DIR")
    if env:
        return Path(expand.value(env))
    from . import manifest
    root = install_root(cwd)
    s = manifest.settings(manifest.load(root))["secrets"]
    legacy = s.get("legacy_env")
    if legacy and os.environ.get(legacy):
        return Path(expand.value(os.environ[legacy]))
    return resolve_config_path(s["default_dir"], root / MANIFEST)
