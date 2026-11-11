"""Config-value expansion: ~, $VAR, ${VAR} and ${VAR:-default}.

    value("${A:-${B:-~/.fleet-secrets}}/key")

No single stdlib call does this: os.path.expandvars knows nothing about `:-` or
`~`, os.path.expanduser knows nothing about variables, and JSON expands nothing.

Rules, each load-bearing:

  * `${VAR:-default}` takes the default when VAR is unset OR EMPTY (shell `:-`
    semantics). A variable exported as "" means "not set"; treating it as a
    value would root the path at "/".
  * The default is itself expanded, so it may hold `$HOME`, `${B}` or another
    `${B:-...}` - nesting is parsed, not iterated to a fixed point.
  * A value taken from the environment is DATA and is never re-scanned. An
    iterate-until-stable expander re-reads a substituted value, so a variable
    whose value contains `${...}` would be expanded again (or, re-introducing
    itself, grow without end).
  * `$VAR` or `${VAR}` naming an unset variable stays LITERAL. The path then
    names a file that does not exist, and the caller's error prints the
    variable nobody set; substituting "" would silently point at a different,
    possibly existing file.
  * A leading `~` (alone or before `/`) expands last, against $HOME, so
    `${X:-~/.x}` works and a variable set to `~/x` (a unit file's Environment=
    expands nothing) does too.
  * Nesting is capped at MAX_DEPTH levels; anything deeper stays literal, so a
    pathological value fails loudly instead of exhausting the stack.
"""

import os
import re

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MAX_DEPTH = 8


def _closing(s, start):
    """Index of the `}` closing a `${` whose body starts at `start`, or None."""
    depth = 0
    i = start
    while i < len(s):
        if s.startswith("${", i):
            depth += 1
            i += 2
            continue
        if s[i] == "}":
            if depth == 0:
                return i
            depth -= 1
        i += 1
    return None


def _expand(s, env, depth):
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "$":
            out.append(c)
            i += 1
            continue
        if s.startswith("${", i):
            m = _NAME.match(s, i + 2)
            if m:
                name, j = m.group(), m.end()
                if s.startswith("}", j):
                    v = env.get(name)
                    out.append(s[i:j + 1] if v is None else v)
                    i = j + 1
                    continue
                if s.startswith(":-", j):
                    end = _closing(s, j + 2)
                    if end is not None:
                        v = env.get(name)
                        if v:
                            out.append(v)
                        elif depth < MAX_DEPTH:
                            out.append(_expand(s[j + 2:end], env, depth + 1))
                        else:
                            out.append(s[i:end + 1])
                        i = end + 1
                        continue
            out.append(c)
            i += 1
            continue
        m = _NAME.match(s, i + 1)
        if m:
            v = env.get(m.group())
            out.append(s[i:m.end()] if v is None else v)
            i = m.end()
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _tilde(s, env):
    if s == "~" or s.startswith("~/"):
        home = env.get("HOME") or os.path.expanduser("~")
        return home + s[1:]
    return s


def value(s, env=None):
    """Expand `s`. `env` defaults to os.environ (tests pass a dict)."""
    if not isinstance(s, str):
        raise TypeError(f"expand.value takes a string, not {type(s).__name__}")
    env = os.environ if env is None else env
    return _tilde(_expand(s, env, 0), env)
