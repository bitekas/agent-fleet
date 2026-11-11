#!/usr/bin/env python3
"""Pick which pool account an agent is signed in with next, and keep the leases.

    pool_pick.py [--agent A] [--current USER] [--auth login|token]
                 [--exclude USER]... [--now EPOCH]
                 [--config C] [--pool F] [--leases F] [--ledger F]
    pool_pick.py --take USER --agent A [--share] [--install-token DEST] [--why TEXT]
                 [--now EPOCH] [--config C] [--pool F] [--leases F]
                 [--handover-ledger F]
    pool_pick.py --release --agent A [--why TEXT] [--config C] [--leases F]
    pool_pick.py --shares [--json] [--roster A,B,...] [--config C] [--pool F] [--leases F]
    pool_pick.py --record --agent A --why TEXT --outcome TEXT [--account USER]
                 [--now EPOCH] [--config C] [--handover-ledger F]
    pool_pick.py --register USER (--token-stdin | --password-stdin)
                 [--home-agent A] [--config C] [--pool F] [--leases F]
    pool_pick.py --read-auth-file F

Every mode prints ONE JSON object on stdout. Usernames, percentages, times,
paths and reasons only: the pool file holds every account's password, a token
file holds an account's token, and this script reads both in-process and never
prints, logs or echoes a byte of either - including in its error messages,
which name an entry by its INDEX and a JSON defect by its line and column,
never by quoting the file.

WHAT THE POOL IS
----------------
The Claude login governs the token quota and nothing else, so the accounts it is
signed in with belong to no agent: they are one pool, held in one file
(`accounts.pool_file` in agent-revive's config.json), a JSON list of
`{"username", "password", "token_file", "home_agent"}`. An entry carries a
PASSWORD (the browser sign-in an agent on the `login` auth mode takes,
agent-revive SKILL.md step 6), a TOKEN FILE (the long-lived token an agent on
the `token` auth mode runs with), or both. `home_agent` is informational and
plays no part in the pick. Which agent holds which account right now is the
LEASE file (`accounts.lease_file`): `{ "<username>": {"agent", "since"} }`.

A token file is an environment file systemd reads (`EnvironmentFile=`), mode
0600, whose leading comment lines say what it is:

    # fleet-auth: token
    # fleet-account: <username>
    CLAUDE_CODE_OAUTH_TOKEN=<the token claude setup-token printed>

An agent's own auth file has the same shape - it is a copy of one pool entry's
token file - so the account it runs as is read off its header with no token
read. `--read-auth-file` is the one reader of that header.

ONE ACCOUNT IS LIVE IN ONE SESSION AT A TIME - while the pool has at least as
many accounts as there are agents. Usage follows the account, so two agents on
one account drain it at twice the rate and neither one's ledger readings mean
anything. A leased account is never a candidate, and a lease is taken and
released only through `--take` and `--release`, under one lock.

SHARED LEASES - ONLY WITH FEWER ACCOUNTS THAN AGENTS
----------------------------------------------------
"Agents" is every agent that holds a lease, plus the one asking. With fewer
accounts than that (one account and two agents; two accounts and four), agents
may share an account, and only as an explicit SHARED LEASE: the lease names
every holder, `{"agents": [..], "since"}` in place of `{"agent", "since"}`. It is
joined only by `--take USER --agent A --share`, which is REFUSED while the pool
has as many accounts as agents - every agent can then hold its own, and a share
would be two sessions draining one account for no reason.
  * The pick offers a share only when no free account qualifies and sharing is
    allowed (`"share": true`, the account it would join).
  * A shared account is read ONCE per sweep and its readings are attributed to
    the account, in the usage ledger section `shared:<account>`, not to an
    agent: `--shares --json` names, per agent, whether to read it and under
    which section (`by_agent`), with one reader per shared account.
  * A handover moves the WHOLE GROUP: picking for an agent whose account is
    shared returns a `group_plan` {holder: target} - one free account per
    holder while free accounts last, the rest sharing the last one; with no
    free account at all, every holder joins the best account another agent
    holds. Each holder is then switched and `--take`n (with `--share` where its
    target already has a holder).
  * `--shares` prints one line per shared account, "N agents share account X",
    which `fleet status` and the install repeat, so a share is never silent; a
    share standing while the pool has as many accounts as agents is reported as
    refused. No pool file, or an install with no agent-revive config at all, is
    no pool: nothing printed (`--json`: the empty view), exit 0. A config named
    by --config or $AGENT_REVIVE_CONFIG that is missing is still exit 2.

THE PICK (exit 0 = a pick, 1 = none, 2 = instrument fault)
----------------------------------------------------------
Deterministic: a function of the pool, the leases, the usage ledger, the
exclude list, the auth mode and the clock, so two operators get the same answer.

1. PREDICT each account's weekly usage from the ledger's LATEST weekly reading
   of that account, in whichever agent's section it was recorded (usage follows
   the account, not the agent). A weekly window is a row whose `Resets` value
   carries a date - `parse_usage.classify_window`, the parser's own rule. Per
   window in that reading: a recorded reset that has PASSED predicts 0%,
   otherwise the reading stands. The account's prediction is the highest of its
   windows. An account with NO weekly row at all is idle: predicted 0%, next
   reset unknown.
2. EXCLUDE the account the agent is on (`--current`), every leased account, every
   account on the exclude list (`accounts.exclude` plus any `--exclude`), every
   account the agent's auth mode cannot use (`--auth login` needs a password,
   `--auth token` a token file), and every account predicted at
   >= EXCLUDE_AT_PCT weekly.
3. Among the rest with at least MIN_HEADROOM_PCT headroom, prefer the SOONEST
   next weekly reset. Headroom that expires at a reset is lost if it is not
   spent, so it is spent first and the long runways stay in reserve. A reset
   that has passed rolls forward in 7-day steps to its next occurrence; an
   unknown reset sorts LAST.
4. Ties go to the account idle longest - the oldest last ledger row of any
   window, and an account never read at all is the idlest of all.

If no account has that much headroom, the least-used of the remainder is picked
(then the same reset and idle order), and the reason says so. If nothing
remains, the pick is null and the exit is 1: the pool is exhausted, which is an
escalation (agent-revive SKILL.md step 5, case 1).

A PREDICTED 0% IS A GUESS ABOUT AN UNREAD ACCOUNT. It is right whenever the
account really was idle, and the first usage reading after the switch replaces
it with a measurement.

RECONCILIATION (`--agent` with `--current`)
-------------------------------------------
Given both, the lease file is checked against the session's real login, and any
disagreement is listed under `problems`, forces the pick to null and exits 1.
A mismatch is an escalation and is never corrected here:
  * the current account is in no pool entry (case 4);
  * the current account is leased to ANOTHER agent - two sessions on one
    account (case 2);
  * the current account carries no lease, or the agent holds a lease on some
    other account - the lease file is out of date (case 2).

THE THREE OUTCOMES, AND WHY 2 IS NOT 1
--------------------------------------
Exit 1 says "the files were read and no account qualifies". Exit 2 says "the
files could not be read", and it pronounces on nothing:
  * A MISSING LEDGER IS EXIT 2, never "every account idle". A mistyped path
    would otherwise predict 0% for every account and pick one that is at 95%.
  * A MISSING LEASE FILE IS EXIT 2, never "nothing leased". Read as empty, it
    makes every live account a candidate and hands an agent the account another
    agent is running on.
  * A missing, malformed or duplicate-carrying pool file is exit 2 (cases 8, 9
    and 10): a guess about which account a broken file meant is a guess about
    which account to sign in with. An entry with neither a usable password (one
    that is missing, empty or whitespace-only is not) nor a token file is
    malformed (case 9): no route can sign it in, so a pool that lists it as
    fine reads as fine until a sign-in fails.

`--take USER --agent A` (exit 0 = taken, 1 = refused, 2 = fault)
----------------------------------------------------------------
Releases every lease A holds (taking A out of a shared one) and leases USER to
A, in one locked read-modify-write that replaces the file atomically, so there
is no moment at which A holds two accounts or none. Refused when USER is in no
pool entry, or is leased to a different agent - unless `--share` is given and
sharing is allowed (SHARED LEASES). Re-taking the account A already holds leaves
its `since` alone. The lease file grows a permanent `<lease file>.lock` beside
it. `--release --agent A` takes A out of every lease it holds (an agent leaving
the fleet), with a ledger row.

  --install-token DEST  copies USER's token file over DEST, the agent's own auth
      file, under the same lock and BEFORE the lease is written, so the lease
      and the token the agent will run with move together or not at all. The
      copy is written to a temporary file created mode 0600 in DEST's directory
      and renamed over DEST; its bytes go from one file to the other in-process
      and nowhere else. Refused unless the entry has a token file that exists,
      is mode 0600 (a token readable by anyone else is already a leaked
      credential, and copying it spreads it) and whose header names USER (a
      header naming another account installs the wrong principal).
  The handover ledger (`accounts.handover_ledger_file`, or --handover-ledger)
  gets one row per take - When, Agent, Old account, New account, Why (--why),
  Outcome (the lease change) - written under the same lock, after the lease.
  A lease change with no row is an agent on an account nobody can explain, so
  the row is part of the take rather than a step somebody remembers. The
  ledger is created with its header on the first row; an install with no
  handover ledger configured gets `"handover_ledger": null` and no row.

`--record --agent A --why TEXT --outcome TEXT` appends one row to the same
ledger for an event that moved no lease: the result of a handover (did the
agent come back working, was its package picked up), a revival that re-signed
the same account, a token reported expired.

`--register USER (--token-stdin | --password-stdin)` (exit 0 = registered,
2 = refused or fault) is the ONE way an account enters the pool. It reads the
credential from standard input - without echo when stdin is a terminal - and
never from an argument, so the credential reaches no command line, history or
transcript. A token must start with `sk-ant-oat` (Claude Code's own test for an
OAuth token), so an API key or a stray line pasted into the prompt is refused.
The token is written to `<tokens dir>/<USER>.env` in the header shape above,
mode 0600 in a 0700 directory (`accounts.tokens_dir`, else
`claude-account-tokens` beside the pool file); a password goes into the entry.
A second call for the same USER adds or replaces that credential and keeps the
other. The pool file is created mode 0600 when absent and is otherwise replaced
atomically with its mode kept; the lease file is created as `{}` and the usage
ledger with its preamble when either is absent, so a registered pool is one the
picker can read.
"""

import argparse
import fcntl
import getpass
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# realpath, never abspath: invoked through an agent's skill link, the unresolved
# path is the link directory, and three levels up from there is not the fleet tree.
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import parse_usage as pu  # noqa: E402 - the ledger's own reader and rules

EXCLUDE_AT_PCT = 80      # a weekly window predicted at or over this is not a candidate
MIN_HEADROOM_PCT = 30    # the soonest-reset preference applies to accounts with this much left
WEEK = timedelta(days=7)
TIME_FMT = pu.TIME_FMT
USERNAME_RE = re.compile(r"^[^\t\n\r]+$")
# The prefix Claude Code itself tests an OAuth token by (`isAnthropicOAuthToken`),
# read from the 2.1.317 binary; `claude setup-token` prints a token of this shape.
TOKEN_PREFIX = "sk-ant-oat"
TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"
AUTH_MODES = ("login", "token")
HANDOVER_COLUMNS = ["When", "Agent", "Old account", "New account", "Why", "Outcome"]
HANDOVER_PREAMBLE = """# handover ledger

One row per account handover, revival or token report. `pool_pick.py --take`
writes a row every time it moves (or confirms) a lease, under the lease lock, so
every lease change has one; `pool_pick.py --record` writes the rows that move
no lease - the outcome of a handover, a token reported expired. The actor of
every row is the agent that ran the command, never the person who authorized it.
Do not delete or rewrite rows: an account switch that is not here did not happen
as far as the next reader is concerned.

"""


class Fault(Exception):
    """An input could not be read. Exit 2; never a verdict about any account."""


def fmt(epoch):
    return None if epoch is None else datetime.fromtimestamp(
        epoch, tz=timezone.utc).strftime(TIME_FMT)


def resolve_path(value, base):
    value = os.path.expanduser(str(value))
    return value if os.path.isabs(value) else os.path.normpath(os.path.join(base, value))


def default_config():
    """agent-revive's config.json in the install context, resolved through fleetlib.

    Its `accounts` block is the one copy of the pool's paths. Resolved only when
    neither --config nor $AGENT_REVIVE_CONFIG names a file, so an explicit path
    needs no install context at all (the offline tests pass one)."""
    sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
    try:
        from fleetlib import paths
        return str(paths.skill_context("agent-revive") / "config.json")
    except Exception as exc:  # noqa: BLE001 - any resolution failure is a config fault
        raise Fault("cannot resolve agent-revive's config.json in the install context "
                    "(%s: %s); pass --config or set AGENT_REVIVE_CONFIG"
                    % (type(exc).__name__, exc))


def load_config(path):
    if not os.path.isfile(path):
        raise Fault("no config at %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except json.JSONDecodeError as exc:
        raise Fault("config %s is not JSON (%s, line %d column %d)"
                    % (path, exc.msg, exc.lineno, exc.colno))
    acc = cfg.get("accounts") if isinstance(cfg, dict) else None
    if not isinstance(acc, dict):
        raise Fault("config %s has no `accounts` object" % path)
    return acc, os.path.dirname(os.path.abspath(path))


def read_pool_raw(path):
    """The pool file's JSON list, unvalidated. Never quotes the file in an error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        # exc.msg / lineno / colno only: str(exc) is safe today, but a message
        # format that ever starts quoting the document would quote a password.
        raise Fault("pool file %s is not one JSON value (%s, line %d column %d) "
                    "- STOP, a guess about a malformed pool is a guess about "
                    "which account to sign in with (case 9)"
                    % (path, exc.msg, exc.lineno, exc.colno))


def load_pool(path):
    """[{username, password, token_file}] in file order, where `password` is only
    WHETHER the entry has a usable one and `token_file` is a resolved path or
    None. Never returns or prints a password or a token.

    An entry with neither a usable password (missing, empty or whitespace-only
    is not) nor a token file is a Fault (case 9), named by its index and
    username: no route can sign it in.
    """
    if not os.path.isfile(path):
        raise Fault("no pool file at %s - no account can be signed in at all; "
                    "that is an escalation, not a switch (agent-revive SKILL.md "
                    "step 5, case 8)" % path)
    raw = read_pool_raw(path)
    if not isinstance(raw, list) or not raw:
        raise Fault("pool file %s must be a non-empty JSON list of "
                    "{username, password, token_file, home_agent} (case 9)" % path)
    base = os.path.dirname(os.path.abspath(path))
    out, seen = [], set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise Fault("pool entry %d is not an object (case 9)" % i)
        user = entry.get("username")
        if not isinstance(user, str) or not USERNAME_RE.match(user):
            raise Fault("pool entry %d has no username, or one that is empty or "
                        "carries a tab or newline (case 9)" % i)
        if "home_agent" in entry and not isinstance(entry["home_agent"], str):
            raise Fault("pool entry %d: home_agent must be a string (case 9)" % i)
        if user in seen:
            raise Fault("pool file %s names %s twice - which entry's password "
                        "signs in is ambiguous (case 10)" % (path, user))
        seen.add(user)
        pw = entry.get("password")
        has_pw = isinstance(pw, str) and bool(pw.strip())
        tf = entry.get("token_file")
        if tf is not None and not (isinstance(tf, str) and tf.strip()):
            raise Fault("pool entry %d (%s): token_file must be a non-empty path "
                        "(case 9)" % (i, user))
        if not has_pw and tf is None:
            raise Fault("pool entry %d (%s) has no password, or an empty or "
                        "whitespace-only one, and no token_file - no route can "
                        "sign it in (case 9)" % (i, user))
        out.append({"username": user, "password": has_pw,
                    "token_file": resolve_path(tf, base) if tf else None})
    return out


def read_auth_header(path):
    """{key: value} from the leading `# key: value` lines of an auth file.

    Reads lines only while they start with `#` and stops at the first that does
    not, so the line carrying the credential is never parsed, kept or printed.
    """
    header = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            m = re.match(r"#\s*(fleet-[a-z-]+):\s*(\S.*?)\s*$", line)
            if m:
                header[m.group(1)] = m.group(2)
    return header


def read_leases(path):
    if not os.path.isfile(path):
        raise Fault("no lease file at %s - read as 'nothing leased' it would "
                    "offer every live account; refusing" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            leases = json.load(fh)
    except json.JSONDecodeError as exc:
        raise Fault("lease file %s is not JSON (%s, line %d column %d)"
                    % (path, exc.msg, exc.lineno, exc.colno))
    if not isinstance(leases, dict):
        raise Fault("lease file %s must be an object keyed by username" % path)
    for user, lease in leases.items():
        if not isinstance(lease, dict):
            raise Fault("lease for %s in %s has no agent" % (user, path))
        if "agents" in lease:
            hs = lease["agents"]
            if not (isinstance(hs, list) and len(hs) >= 2 and len(set(hs)) == len(hs)
                    and all(isinstance(h, str) and h for h in hs)):
                raise Fault("shared lease for %s in %s must name two or more distinct "
                            "agents" % (user, path))
        elif not (isinstance(lease.get("agent"), str) and lease["agent"]):
            raise Fault("lease for %s in %s has no agent" % (user, path))
    return leases


def holders(lease):
    """Every agent a lease names: one, or the holders of a shared lease."""
    if not lease:
        return []
    return list(lease["agents"]) if "agents" in lease else [lease["agent"]]


def lease_entry(hs, since):
    """The lease for these holders: `agent` for one, a shared `agents` list for more."""
    hs = sorted(set(hs))
    return {"agent": hs[0], "since": since} if len(hs) == 1 else {"agents": hs, "since": since}


def head_count(pool, leases, agent=None):
    """(accounts, agents): the pool's size, and every agent a lease names plus the
    one asking. Sharing is allowed only while accounts < agents."""
    agents = {h for l in leases.values() for h in holders(l)}
    if agent:
        agents.add(agent)
    return len(pool), len(agents)


SHARED_SECTION = "shared:"


def ledger_rows_by_account(path):
    """{account: [row, ...]} over EVERY agent section, each row with an epoch."""
    if not os.path.isfile(path):
        raise Fault("ledger not found: %s - read as 'no history' it would "
                    "predict 0%% for every account; refusing" % path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        sections = sorted({l.strip()[3:].strip() for l in fh
                           if l.startswith("## ")})
    by_account = {}
    for agent in sections:
        try:
            rows = pu.read_ledger_rows(path, agent)
        except pu.LedgerError as exc:
            raise Fault("LEDGER FAULT: %s" % exc)
        for row in rows:
            try:
                row["epoch"] = datetime.strptime(row["time"], TIME_FMT).replace(
                    tzinfo=timezone.utc).timestamp()
                row["pct"] = int(row["percent"])
            except ValueError:
                raise Fault("%s:%d: a row in section '%s' has an unreadable time "
                            "or percentage" % (path, row["line"], agent))
            by_account.setdefault(row["account"], []).append(row)
    return by_account


def predict(rows, now):
    """The weekly prediction for one account from its ledger rows."""
    if not rows:
        return {"predicted_weekly_pct": 0, "reading_at": None, "next_reset": None,
                "last_seen": None, "basis": "no ledger row - idle, predicted 0%"}
    last_seen = max(r["epoch"] for r in rows)
    weekly = [r for r in rows if pu.classify_window(r["resets"]) == "long"]
    if not weekly:
        return {"predicted_weekly_pct": 0, "reading_at": None, "next_reset": None,
                "last_seen": last_seen,
                "basis": "no weekly row - predicted 0%, reset unknown"}
    at = max(r["epoch"] for r in weekly)
    windows = []
    for r in (r for r in weekly if r["epoch"] == at):
        reset = pu.resolve_reset(r["resets"], r["epoch"])
        if reset is not None and reset <= now:
            steps = int((now - reset) // WEEK.total_seconds()) + 1
            windows.append((0, reset + steps * WEEK.total_seconds(), True))
        else:
            windows.append((r["pct"], reset, False))
    top = max(w[0] for w in windows)
    resets = [w[1] for w in windows if w[0] == top and w[1] is not None]
    passed = any(w[2] for w in windows)
    basis = "weekly reading of %s" % fmt(at)
    if passed:
        basis += ", a recorded reset has passed since"
    return {"predicted_weekly_pct": top, "reading_at": at,
            "next_reset": min(resets) if resets else None,
            "last_seen": last_seen, "basis": basis}


def pick(pool, leases, rows_by_account, excluded, now, current=None, agent=None,
         auth="login"):
    accounts, problems = [], []
    pool_names = [e["username"] for e in pool]
    if current is not None and current not in pool_names:
        problems.append("current account %s is in no pool entry - STOP and "
                        "escalate (agent-revive SKILL.md step 5, case 4)" % current)
    if agent is not None and current is not None:
        hs = holders(leases.get(current))
        if hs and agent not in hs:
            problems.append("current account %s is leased to %s, not %s - two "
                            "sessions on one account (case 2)" % (current, ", ".join(hs), agent))
        elif not hs and current in pool_names:
            problems.append("current account %s carries no lease - the lease file "
                            "is out of date (case 2)" % current)
        others = sorted(u for u, l in leases.items()
                        if agent in holders(l) and u != current)
        if others:
            problems.append("%s also holds a lease on %s, but its session is on %s "
                            "(case 2)" % (agent, ", ".join(others), current))

    def fit(e, p):
        """(status, note) by every rule but the lease: what a free account would be."""
        user = e["username"]
        if user in excluded:
            return "excluded", "excluded: %s" % excluded[user]
        if auth == "token" and not e["token_file"]:
            return "unusable", ("no token file - a token agent switches by installing the "
                                "account's token, and this entry has none")
        if auth == "login" and not e["password"]:
            return "unusable", ("no password - a login agent signs in through the browser "
                                "with the account's password, and this entry has none")
        if p["predicted_weekly_pct"] >= EXCLUDE_AT_PCT:
            return "over-limit", "predicted weekly %d%% >= %d%% (%s)" % (
                p["predicted_weekly_pct"], EXCLUDE_AT_PCT, p["basis"])
        if 100 - p["predicted_weekly_pct"] >= MIN_HEADROOM_PCT:
            return "candidate", p["basis"]
        return "low-headroom", "predicted weekly %d%%, headroom under %d%% (%s)" % (
            p["predicted_weekly_pct"], MIN_HEADROOM_PCT, p["basis"])

    for e in pool:
        user = e["username"]
        p = predict(rows_by_account.get(user, []), now)
        hs = holders(leases.get(user))
        entry = {"username": user, "status": None,
                 "leased_by": ",".join(hs) if hs else None,
                 "predicted_weekly_pct": p["predicted_weekly_pct"],
                 "reading_at": fmt(p["reading_at"]),
                 "next_reset": fmt(p["next_reset"]),
                 "last_seen": fmt(p["last_seen"]),
                 "credentials": [k for k in ("password", "token_file") if e[k]],
                 "note": p["basis"],
                 "_reset": p["next_reset"], "_seen": p["last_seen"], "_fit": None}
        if user == current:
            entry["status"], entry["note"] = "current", "the account the session is on"
            if len(hs) > 1:
                entry["note"] += ", shared by %s" % ", ".join(hs)
        elif hs:
            entry["status"] = "leased"
            entry["note"] = "leased to %s since %s" % (", ".join(hs), leases[user].get("since", "?"))
            entry["_fit"] = fit(e, p)[0]
        else:
            entry["status"], entry["note"] = fit(e, p)
        accounts.append(entry)

    # Unknown reset sorts LAST; never-seen sorts as the idlest (-inf).
    def order(e):
        return (e["_reset"] is None, e["_reset"] or 0,
                e["_seen"] if e["_seen"] is not None else float("-inf"))

    tier1 = sorted((e for e in accounts if e["status"] == "candidate"), key=order)
    tier2 = sorted((e for e in accounts if e["status"] == "low-headroom"),
                   key=lambda e: (e["predicted_weekly_pct"],) + order(e))
    ranked = tier1 or tier2
    for rank, e in enumerate(ranked, start=1):
        e["rank"] = rank
    for e in tier1:
        e["note"] = "rank %d: predicted weekly %d%%, next weekly reset %s (%s)" % (
            e["rank"], e["predicted_weekly_pct"], e["next_reset"] or "unknown", e["note"])

    n_accounts, n_agents = head_count(pool, leases, agent)
    sharing = {"accounts": n_accounts, "agents": n_agents, "allowed": n_accounts < n_agents}
    # Accounts another agent holds, ranked as free ones would be: what a share joins.
    share_ranked = (sorted((e for e in accounts if e["_fit"] == "candidate"), key=order)
                    or sorted((e for e in accounts if e["_fit"] == "low-headroom"),
                              key=lambda e: (e["predicted_weekly_pct"],) + order(e)))
    group = sorted(holders(leases.get(current))) if current else []
    group_plan = None
    if len(group) > 1 and not problems:
        # THE WHOLE GROUP MOVES: one free account per holder while they last, the
        # rest sharing the last; with none free, every holder joins the best
        # account another agent holds.
        targets = [e["username"] for e in ranked] or [e["username"] for e in share_ranked[:1]]
        if targets:
            plan = {h: targets[min(i, len(targets) - 1)] for i, h in enumerate(group)}
            held = {u for u, l in leases.items() if holders(l) and u != current}
            group_plan = {h: {"to": t, "share": t in held or list(plan.values()).count(t) > 1}
                          for h, t in plan.items()}

    chosen, reason, share = None, "", False
    if problems:
        reason = "no pick: the leases disagree with the session - " + "; ".join(problems)
    elif group_plan and agent in group_plan:
        chosen, share = group_plan[agent]["to"], group_plan[agent]["share"]
        reason = ("%s - %s's account %s is shared by %s, and a handover moves the whole "
                  "group: %s" % (chosen, agent, current, ", ".join(group),
                                 "; ".join("%s -> %s%s" % (h, v["to"], " (shared)" if v["share"] else "")
                                           for h, v in group_plan.items())))
    elif not ranked and sharing["allowed"] and share_ranked:
        chosen, share = share_ranked[0]["username"], True
        reason = ("%s - no free account qualifies and the pool has %d account(s) for %d "
                  "agent(s), so %s joins it as a SHARED lease (take it with --share); "
                  "held by %s" % (chosen, n_accounts, n_agents, agent or "the agent",
                                  share_ranked[0]["leased_by"]))
    elif not ranked:
        reason = ("pool exhausted: every account is current, leased, excluded, "
                  "unusable on the %s auth mode or predicted at >= %d%% weekly%s - "
                  "STOP and escalate with the soonest reset below (case 1)"
                  % (auth, EXCLUDE_AT_PCT,
                     "" if sharing["allowed"] else ", and sharing is refused with %d "
                     "account(s) for %d agent(s)" % (n_accounts, n_agents)))
    else:
        c = ranked[0]
        chosen = c["username"]
        if tier1:
            reason = ("%s - %s - the soonest reset among %d account(s) with >= %d%% "
                      "headroom" % (chosen, c["note"], len(tier1), MIN_HEADROOM_PCT))
        else:
            reason = ("%s - %s, next weekly reset %s - NO account has >= %d%% "
                      "headroom, so this is the least-used of %d below %d%%"
                      % (chosen, c["note"], c["next_reset"] or "unknown",
                         MIN_HEADROOM_PCT, len(tier2), EXCLUDE_AT_PCT))
        if len(ranked) > 1 and ranked[1]["_reset"] == c["_reset"]:
            reason += "; tie on the reset, broken by idle-longest (last seen %s)" % (
                c["last_seen"] or "never")
    for e in accounts:
        del e["_reset"], e["_seen"], e["_fit"]
    return {"now": fmt(now), "agent": agent, "current": current, "auth": auth,
            "pick": chosen, "share": share, "group_plan": group_plan, "sharing": sharing,
            "reason": reason, "problems": problems,
            "thresholds": {"exclude_at_pct": EXCLUDE_AT_PCT,
                           "min_headroom_pct": MIN_HEADROOM_PCT},
            "accounts": accounts}


# --------------------------------------------------------------------------
# writes: every one goes through a temporary file and a rename
# --------------------------------------------------------------------------

def replace_file(path, data, mode):
    """Write `data` (bytes) to `path` atomically with `mode`.

    The temporary file is created by mkstemp, which opens it 0600, and gets its
    final mode before a byte is written, so no moment exists at which a
    credential sits in a file anyone else can read.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pool-pick-", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def lock(path):
    fh = open(path + ".lock", "a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def cell(value):
    return str(value).replace("|", "/").replace("\n", " ").strip() or "-"


def append_handover_row(path, row):
    """One row under the handover ledger's table, creating the file on the first."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if text and not text.endswith("\n"):
            text += "\n"
    else:
        text = (HANDOVER_PREAMBLE + "| " + " | ".join(HANDOVER_COLUMNS) + " |\n"
                + "|" + "|".join(["---"] * len(HANDOVER_COLUMNS)) + "|\n")
    text += "| " + " | ".join(cell(c) for c in row) + " |\n"
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else 0o644
    replace_file(path, text.encode("utf-8"), mode)


def check_writable_dir(path, what):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(directory) or not os.access(directory, os.W_OK):
        raise Fault("%s %s: its directory %s does not exist or is not writable"
                    % (what, path, directory))


def token_source(entry, user):
    """The validated token file of `entry`, or (None, reason)."""
    tf = entry["token_file"]
    if not tf:
        return None, "%s has no token_file in the pool - nothing to install" % user
    if not os.path.isfile(tf):
        return None, "%s's token file %s does not exist" % (user, tf)
    if stat.S_IMODE(os.stat(tf).st_mode) & 0o077:
        return None, ("%s's token file %s is readable by others (mode %o) - a token "
                      "anyone else can read is already a leaked credential; fix its "
                      "mode to 600 and have the token rotated"
                      % (user, tf, stat.S_IMODE(os.stat(tf).st_mode)))
    header = read_auth_header(tf)
    if header.get("fleet-auth") != "token" or header.get("fleet-account") != user:
        return None, ("%s's token file %s does not carry the header '# fleet-auth: "
                      "token' and '# fleet-account: %s' - installing it could sign the "
                      "agent in as another principal" % (user, tf, user))
    return tf, None


def take(lease_path, pool, user, agent, now, install_to=None, why="-",
         handover_ledger=None, share=False):
    entries = {e["username"]: e for e in pool}
    if user not in entries:
        return 1, {"taken": None, "agent": agent,
                   "reason": "%s is in no pool entry - refusing to lease it" % user}
    fh = lock(lease_path)
    try:
        leases = read_leases(lease_path)
        hs = holders(leases.get(user))
        others = [h for h in hs if h != agent]
        # Joining means another agent holds it and this one does not: a holder
        # re-taking its own shared lease (a revival on the same account) joins nothing.
        joining = bool(others) and agent not in hs
        if joining and not share:
            return 1, {"taken": None, "agent": agent,
                       "reason": "%s is leased to %s - refusing: one account is "
                                 "live in one session at a time unless it is joined "
                                 "as a shared lease (--share)" % (user, ", ".join(others))}
        if joining:
            n_accounts, n_agents = head_count(pool, leases, agent)
            if n_accounts >= n_agents:
                return 1, {"taken": None, "agent": agent,
                           "reason": "%s is leased to %s - sharing is REFUSED: the pool has "
                                     "%d account(s) for %d agent(s), so every agent can "
                                     "hold its own" % (user, ", ".join(others), n_accounts,
                                                       n_agents)}
        src = None
        if install_to is not None:
            src, why_not = token_source(entries[user], user)
            if src is None:
                return 1, {"taken": None, "agent": agent, "reason": why_not}
            if os.path.realpath(src) == os.path.realpath(install_to):
                return 1, {"taken": None, "agent": agent,
                           "reason": "--install-token names the pool's own token file"}
            check_writable_dir(install_to, "auth file")
        if handover_ledger:
            check_writable_dir(handover_ledger, "handover ledger")
        released = drop_holder(leases, agent, keep=user)
        unchanged = agent in hs
        if not unchanged:
            leases[user] = lease_entry(hs + [agent], leases[user]["since"] if hs else fmt(now))
        if src is not None:
            with open(src, "rb") as tfh:
                replace_file(install_to, tfh.read(), 0o600)
        mode = stat.S_IMODE(os.stat(lease_path).st_mode)
        replace_file(lease_path, (json.dumps(leases, indent=2, sort_keys=True)
                                  + "\n").encode("utf-8"), mode)
        out = {"taken": user, "agent": agent, "released": released,
               "unchanged": unchanged, "since": leases[user].get("since"),
               "shared_with": others,
               "token_installed": install_to if src is not None else None,
               "handover_ledger": handover_ledger}
        if handover_ledger:
            old = ", ".join(released) if released else (user if unchanged else "-")
            outcome = ("lease unchanged on %s" % user if unchanged else
                       "lease moved: released %s, took %s"
                       % (", ".join(released) or "nothing", user))
            if others and not unchanged:
                outcome += " as a SHARED lease with %s" % ", ".join(others)
            if src is not None:
                outcome += "; token installed at %s" % install_to
            try:
                append_handover_row(handover_ledger,
                                    [fmt(now), agent, old, user, why, outcome])
            except OSError as exc:
                raise Fault("the lease MOVED (%s) but its handover-ledger row was not "
                            "written: %s - add the row with --record" % (outcome, exc))
        return 0, out
    finally:
        fh.close()


def drop_holder(leases, agent, keep=None):
    """Take `agent` out of every lease but `keep`'s, in place; a shared lease left
    with one holder becomes that holder's own. Returns the accounts released."""
    released = []
    for u in sorted(leases):
        hs = holders(leases[u])
        if u == keep or agent not in hs:
            continue
        released.append(u)
        rest = [h for h in hs if h != agent]
        if rest:
            leases[u] = lease_entry(rest, leases[u].get("since"))
        else:
            del leases[u]
    return released


def release(lease_path, agent, why, handover_ledger, now):
    """Take `agent` out of every lease it holds - an agent leaving the fleet."""
    fh = lock(lease_path)
    try:
        leases = read_leases(lease_path)
        if handover_ledger:
            check_writable_dir(handover_ledger, "handover ledger")
        released = drop_holder(leases, agent)
        if released:
            replace_file(lease_path, (json.dumps(leases, indent=2, sort_keys=True) + "\n")
                         .encode("utf-8"), stat.S_IMODE(os.stat(lease_path).st_mode))
            if handover_ledger:
                append_handover_row(handover_ledger, [fmt(now), agent, ", ".join(released),
                                                      "-", why, "released, no account"])
        return 0, {"released": released, "agent": agent, "handover_ledger": handover_ledger}
    finally:
        fh.close()


def shares(pool, leases, roster=None):
    """The machine-readable view of every shared lease, and how the sweep reads it.

    One shared lease is read ONCE per sweep, by one of its holders (the first, in
    name order, that is in `roster` when a roster is given), and its readings go
    to the usage-ledger section SHARED_SECTION + account. `by_agent` says, for every
    agent a lease names, whether this sweep reads it and under which section.
    """
    n_accounts, n_agents = head_count(pool, leases)
    allowed = n_accounts < n_agents
    out, by_agent = [], {}
    for u in sorted(leases):
        hs = sorted(holders(leases[u]))
        if len(hs) < 2:
            by_agent[hs[0]] = {"account": u, "section": hs[0], "read": True, "covered_by": None}
            continue
        live = [h for h in hs if roster is None or h in roster]
        reader = live[0] if live else None
        section = SHARED_SECTION + u
        line = "%d agents share account %s (%s)" % (len(hs), u, ", ".join(hs))
        if not allowed:
            line += (" - sharing is REFUSED with %d account(s) for %d agent(s): move one "
                     "to a free account" % (n_accounts, n_agents))
        out.append({"account": u, "agents": hs, "section": section, "reader": reader,
                    "allowed": allowed, "line": line})
        for h in hs:
            by_agent[h] = {"account": u, "section": section, "read": h == reader,
                           "covered_by": None if h == reader else reader}
    return {"accounts": n_accounts, "agents": n_agents, "sharing_allowed": allowed,
            "shares": out, "by_agent": by_agent}


def record(handover_ledger, agent, account, why, outcome, now):
    check_writable_dir(handover_ledger, "handover ledger")
    fh = lock(handover_ledger)
    try:
        append_handover_row(handover_ledger,
                            [fmt(now), agent, account or "-", account or "-", why, outcome])
    finally:
        fh.close()
    return 0, {"recorded": True, "agent": agent, "handover_ledger": handover_ledger}


def read_secret(what):
    """One line from stdin: without echo on a terminal, else the first line."""
    if sys.stdin.isatty():
        value = getpass.getpass("paste the %s for this account, then Enter: " % what)
    else:
        value = sys.stdin.readline()
    return value.strip()


def register(pool_path, lease_path, ledger_path, tokens_dir, user, kind, home_agent):
    if not USERNAME_RE.match(user) or "/" in user or user.startswith("."):
        raise Fault("%r cannot be a pool username: it is empty, carries a tab, a "
                    "newline or a slash, or starts with a dot" % user)
    secret = read_secret("token" if kind == "token" else "password")
    if not secret:
        raise Fault("nothing was read from standard input - nothing registered")
    if kind == "token" and (not secret.startswith(TOKEN_PREFIX)
                            or re.search(r"\s", secret) or len(secret) < 40):
        raise Fault("what was read is not a Claude OAuth token (it must start with "
                    "%s, as `claude setup-token` prints it, with no space) - nothing "
                    "registered" % TOKEN_PREFIX)
    # Every file this call may create is checked BEFORE the first write, so a
    # refusal leaves no half-made pool behind (a pool with no lease file is one
    # the picker refuses to read).
    for p, what in ((lease_path, "lease file"), (ledger_path, "usage ledger")):
        if p and not os.path.exists(p):
            check_writable_dir(p, what)
    created = []
    pool_dir = os.path.dirname(os.path.abspath(pool_path))
    if not os.path.isdir(pool_dir):
        os.makedirs(pool_dir, mode=0o700)
        created.append(pool_dir)
    fh = lock(pool_path)
    try:
        if os.path.exists(pool_path):
            load_pool(pool_path)          # refuses a malformed pool before touching it
            raw = read_pool_raw(pool_path)
            mode = stat.S_IMODE(os.stat(pool_path).st_mode)
        else:
            raw, mode = [], 0o600
            created.append(pool_path)
        entry = next((e for e in raw if isinstance(e, dict) and e.get("username") == user), None)
        if entry is None:
            entry = {"username": user}
            raw.append(entry)
        if home_agent:
            entry["home_agent"] = home_agent
        token_file = None
        if kind == "token":
            if not os.path.isdir(tokens_dir):
                os.makedirs(tokens_dir, mode=0o700)
                created.append(tokens_dir)
            token_file = os.path.join(tokens_dir, user + ".env")
            replace_file(token_file, ("# fleet-auth: token\n# fleet-account: %s\n%s=%s\n"
                                      % (user, TOKEN_VAR, secret)).encode("utf-8"), 0o600)
            entry["token_file"] = token_file
        else:
            entry["password"] = secret
        replace_file(pool_path, (json.dumps(raw, indent=2) + "\n").encode("utf-8"), mode)
    finally:
        fh.close()
    if not os.path.exists(lease_path):
        check_writable_dir(lease_path, "lease file")
        replace_file(lease_path, b"{}\n", 0o600)
        created.append(lease_path)
    if ledger_path and not os.path.exists(ledger_path):
        check_writable_dir(ledger_path, "usage ledger")
        replace_file(ledger_path, pu.LEDGER_PREAMBLE.encode("utf-8"), 0o644)
        created.append(ledger_path)
    return 0, {"registered": user, "credential": kind, "token_file": token_file,
               "pool_file": pool_path, "accounts": len(raw), "created": created}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pool_pick.py", description=__doc__.split("\n")[0])
    ap.add_argument("--config",
                    help="agent-revive's config.json (its `accounts` block); default "
                         "$AGENT_REVIVE_CONFIG, else the install context's copy")
    ap.add_argument("--pool", help="override accounts.pool_file")
    ap.add_argument("--leases", help="override accounts.lease_file")
    ap.add_argument("--ledger", help="override accounts.ledger_file")
    ap.add_argument("--handover-ledger", help="override accounts.handover_ledger_file")
    ap.add_argument("--agent", help="the agent being signed in")
    ap.add_argument("--current", help="the account its session is on now")
    ap.add_argument("--auth", choices=AUTH_MODES, default="login",
                    help="the agent's auth mode: login (a browser sign-in, needs a "
                         "password) or token (a long-lived token, needs a token file)")
    ap.add_argument("--exclude", action="append", default=[], metavar="USER",
                    help="exclude this account too (repeatable), e.g. one already "
                         "tried and found capped during this revival")
    ap.add_argument("--take", metavar="USER",
                    help="lease USER to --agent, releasing its other leases")
    ap.add_argument("--share", action="store_true",
                    help="with --take: join USER as a SHARED lease when another agent holds "
                         "it - refused while the pool has as many accounts as agents")
    ap.add_argument("--release", action="store_true",
                    help="take --agent out of every lease it holds")
    ap.add_argument("--shares", action="store_true",
                    help="every shared lease, one line each, and how the sweep reads it")
    ap.add_argument("--json", action="store_true", help="with --shares: one JSON object")
    ap.add_argument("--roster", help="with --shares: the agents with a live session, "
                                     "comma-separated; a shared account's reader is one of them")
    ap.add_argument("--install-token", metavar="DEST",
                    help="with --take: copy USER's token file over DEST, the agent's "
                         "auth file, under the lease lock")
    ap.add_argument("--why", default="-", help="the handover ledger's Why column")
    ap.add_argument("--record", action="store_true",
                    help="append one handover-ledger row that moves no lease")
    ap.add_argument("--outcome", help="with --record: the Outcome column")
    ap.add_argument("--account", help="with --record: the account the row is about")
    ap.add_argument("--register", metavar="USER",
                    help="add USER to the pool, or add a credential to its entry")
    cred = ap.add_mutually_exclusive_group()
    cred.add_argument("--token-stdin", action="store_true",
                      help="with --register: read the account's setup-token from stdin")
    cred.add_argument("--password-stdin", action="store_true",
                      help="with --register: read the account's password from stdin")
    ap.add_argument("--home-agent", help="with --register: the informational home_agent")
    ap.add_argument("--read-auth-file", metavar="F",
                    help="print the auth mode and account an auth file's header names")
    ap.add_argument("--now", type=float, default=None,
                    help="override the clock, epoch seconds (tests)")
    args = ap.parse_args(argv)
    now = args.now if args.now is not None else datetime.now(tz=timezone.utc).timestamp()

    if args.read_auth_file:
        f = args.read_auth_file
        if not os.path.isfile(f):
            raise Fault("no auth file at %s" % f)
        h = read_auth_header(f)
        print(json.dumps({"file": f, "auth": h.get("fleet-auth"),
                          "account": h.get("fleet-account")}))
        return 0 if h.get("fleet-auth") else 1

    named = args.config or os.environ.get("AGENT_REVIVE_CONFIG")
    config = named or default_config()
    no_pool = {"pool": None, "accounts": 0, "agents": 0, "sharing_allowed": False,
               "shares": [], "by_agent": {}}

    def print_shares(view):
        if args.json:
            print(json.dumps(view, indent=2))
        else:
            for s in view["shares"]:
                print(s["line"])
        return 0

    if args.shares and not named and not os.path.isfile(config):
        # An install with no agent-revive config has no pool, so nothing is
        # shared: the status line and the install's closing summary that ask get
        # nothing, exit 0. A config named by --config or $AGENT_REVIVE_CONFIG
        # that is not there stays a fault (a typo is not "no pool"), and so does
        # a missing config in every other mode.
        return print_shares(no_pool)
    acc, base = load_config(config)

    def path(flag, key, required=True):
        if flag:
            return flag
        if not acc.get(key):
            if not required:
                return None
            raise Fault("config %s has no accounts.%s" % (config, key))
        return resolve_path(acc[key], base)

    handover = path(args.handover_ledger, "handover_ledger_file", required=False)

    if args.record:
        if not (args.agent and args.outcome and args.why != "-"):
            raise Fault("--record needs --agent, --why and --outcome")
        if not handover:
            raise Fault("--record needs a handover ledger: accounts.handover_ledger_file "
                        "in %s, or --handover-ledger" % config)
        rc, out = record(handover, args.agent, args.account, args.why, args.outcome, now)
        print(json.dumps(out, indent=2))
        return rc

    if args.register:
        if not (args.token_stdin or args.password_stdin):
            raise Fault("--register needs --token-stdin or --password-stdin: an entry "
                        "with no credential is one no route can sign in (case 9)")
        pool_path = path(args.pool, "pool_file")
        tokens_dir = (resolve_path(acc["tokens_dir"], base) if acc.get("tokens_dir")
                      else os.path.join(os.path.dirname(os.path.abspath(pool_path)),
                                        "claude-account-tokens"))
        rc, out = register(pool_path, path(args.leases, "lease_file"),
                           path(args.ledger, "ledger_file", required=False), tokens_dir,
                           args.register, "token" if args.token_stdin else "password",
                           args.home_agent)
        print(json.dumps(out, indent=2))
        return rc

    if args.shares:
        # A pool that does not exist has nothing shared: an install with no pool is
        # not a fault to the status line that asks.
        pool_path = path(args.pool, "pool_file")
        if not os.path.exists(pool_path):
            return print_shares(no_pool)
        roster = [r for r in (args.roster or "").split(",") if r] if args.roster else None
        return print_shares(dict(shares(load_pool(pool_path), read_leases(path(args.leases, "lease_file")),
                                        roster), pool=pool_path))

    pool = load_pool(path(args.pool, "pool_file"))
    lease_path = path(args.leases, "lease_file")

    if args.release:
        if not args.agent:
            raise Fault("--release needs --agent")
        rc, out = release(lease_path, args.agent, args.why, handover, now)
        print(json.dumps(out, indent=2))
        return rc

    if args.take:
        if not args.agent:
            raise Fault("--take needs --agent")
        rc, out = take(lease_path, pool, args.take, args.agent, now,
                       install_to=args.install_token, why=args.why,
                       handover_ledger=handover, share=args.share)
        print(json.dumps(out, indent=2))
        return rc

    excluded = {}
    for e in acc.get("exclude") or []:
        if isinstance(e, dict) and isinstance(e.get("username"), str):
            excluded[e["username"]] = e.get("reason") or "on accounts.exclude"
        elif isinstance(e, str):
            excluded[e] = "on accounts.exclude"
        elif not (isinstance(e, dict) and set(e) <= {"_comment"}):
            raise Fault("accounts.exclude entries are {username, reason} objects")
    for u in args.exclude:
        excluded.setdefault(u, "--exclude")

    result = pick(pool, read_leases(lease_path),
                  ledger_rows_by_account(path(args.ledger, "ledger_file")),
                  excluded, now, current=args.current, agent=args.agent,
                  auth=args.auth)
    print(json.dumps(result, indent=2))
    return 0 if result["pick"] else 1


def main_guarded(argv=None):
    """Every fault is exit 2 with a message on stderr and a null pick on stdout."""
    try:
        return main(argv)
    except Fault as exc:
        msg = str(exc)
    except OSError as exc:
        msg = "I/O: %s" % exc
    except Exception as exc:  # noqa: BLE001 - an instrument that fell over pronounces nothing
        msg = "%s: %s" % (type(exc).__name__, exc)
    sys.stderr.write("pool_pick.py: INSTRUMENT FAULT - %s\n" % msg)
    print(json.dumps({"pick": None, "taken": None, "fault": msg}))
    return 2


if __name__ == "__main__":
    sys.exit(main_guarded())
