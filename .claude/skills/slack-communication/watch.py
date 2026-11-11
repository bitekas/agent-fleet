#!/usr/bin/env python3
"""Slack multi-channel watcher - the poller behind the agent's live Slack inbox.

Polls Slack with the configured bot token and prints ONE LINE per new
DELIVERABLE message (top-level or thread reply): every message from anyone but
this bot itself. Designed to run under a Claude Code
persistent Monitor: each printed line is injected into the agent's session as a
wake-up event, which is how Slack messages reach the agent near-real-time
(~POLL_SECS latency; longer for a reply whose thread parent is off the poll's
page - SKILL.md) without any public endpoint. Mechanics (IDs, token, posting
recipes, this script's contract): SKILL.md beside this file. Policy (who may
request what, triage): the owning agent's charter, which the install's
CONTEXT.md for this skill names.

Channel autodiscovery (no hardcoded channel list):
  The watcher polls EVERY channel the bot is a member of - PUBLIC and PRIVATE
  alike - discovered at runtime via `users.conversations`
  (`types=public_channel,private_channel`, one call returns both) and
  re-discovered every ~60s inside the poll loop - so `/invite`-ing the bot to a
  new channel (public or private) subscribes it WITHOUT a restart, and `/kick`
  unsubscribes it. **`/invite` (by a workspace human) is the subscription
  mechanism** - the bot has no `channels:join` scope and cannot add itself.
  Private channels emit identically to public ones (`SLACK #<name> ...`). No
  channel is privileged: discovery owns the watched set outright, there is no
  seeded home/default channel. On a discovery failure the watcher keeps polling
  the last known channel set (and never crashes). The one edge that follows: if
  the very FIRST discovery of a process fails or returns empty, the watched set
  is empty for that cycle and the watcher polls NOTHING, self-healing on the next
  ~60s rediscovery. Last-seen cursors are per-conversation files on disk (see
  State below), so whatever arrived during the gap is emitted by the first poll
  that does see the channel, back as far as THE WINDOW BOUND below allows.
  If the combined-types call ever loses the private scope (groups:read) it
  degrades to public-only with one logged line, re-probing combined types each
  rediscovery.

Direct messages (DMs to the bot):
  If the bot install has the `im:read` + `im:history` scopes, the same
  `users.conversations` discovery (a second call with `types=im`) picks up every
  open IM conversation with the bot, and DM messages emit as `SLACK DM ...` lines
  (unmistakably not a channel). If the scopes are absent (reinstall pending),
  the `types=im` probe returns `missing_scope`: the watcher logs ONE stderr line,
  falls back to channels-only, and re-probes on the normal ~60s rediscovery
  cadence - so DMs light up automatically once the scopes are granted, with no
  restart. (Private CHANNELS are covered by the combined channel-discovery call
  above - this fallback note is about IM/DMs only.)

Threads off the page, the catch-up, the sweep and THE WINDOW BOUND:
  How a reply is read when its parent has more newer top-level posts above it
  than the poll's 50-message page holds, how a poll catches up after downtime,
  what both cost per poll, and what is still not read: SKILL.md, "Threads off
  the page, and the sweep". That section is the one statement of it.

Retiring a conversation Slack says is gone:
  A per-conversation poll failure is caught so one bad conversation cannot kill
  the whole watch - but a PERMANENT failure then repeats every POLL_SECS forever.
  (Real instance: a DM that stays in `users.conversations` discovery while
  `conversations.history` on it answers `channel_not_found` for a bot token.) So
  when a poll fails with such an error (`GONE_CONVERSATION_ERRORS`), that
  conversation is RETIRED for the rest of the process: ONE
  `WATCH-INFO retired ... (<id>): Slack says <reason>` line, and no further polls
  or lines for it. Every other exception keeps the per-poll `WATCH-ERROR` -
  deliberately, because a fault that can end needs repetition to show it has not
  ended. A retirement survives rediscovery while the conversation is still
  discovered; if it drops out of discovery and later returns, it is probed once
  more. Retirement is process-scoped, so a restart re-probes everything.
  ⚠️ The membership test for that set is NOT "is this error permanent?" but "is
  this an error DISCOVERY WILL NOT NOTICE?" - a kicked bot (`not_in_channel`) and
  an archived channel (`is_archived`) both leave the watched set at the next
  ~60s rediscovery on their own, so retiring them would buy ~12 suppressed lines
  and risk retiring a LIVE conversation forever on a transient. The set and that
  argument are at `GONE_CONVERSATION_ERRORS` below; read it before adding a code.
  ⚠️ The cost of a retirement: that conversation is watched by NOTHING until the
  watcher restarts, its one line is the only notice, and its cursor stops
  advancing - so if it is ever un-retired by leaving and re-entering discovery,
  the backlog it resumes from is subject to THE WINDOW BOUND (SKILL.md) like
  any other gap.

Usage (from any directory; <skill dir> is the directory holding this file):
  SLACK_WATCH_CONFIG=<config> python3 <skill dir>/watch.py          # poll loop (the service)
  SLACK_WATCH_CONFIG=<config> python3 <skill dir>/watch.py --once   # one poll + one full sweep
                                                  # (smoke test; ⚠️ writes the cursors - SKILL.md)

Is it armed?  pgrep -af "[s]lack-communication/watch.py"     (macOS: pgrep -fl)

State (last-seen ts per thread) lives in one file PER CHANNEL,
<state.dir>/<state.prefix>-<channel_id>.json, so a re-armed monitor in a new
session does NOT replay old messages. A channel seen for the first time (no state
file yet) is baselined by looking for the bot's OWN channel_join marker in a
short recent window (RECENT_JOIN_WINDOW_SECS): if the bot was just invited, the
cursor is set to the join ts and deliverable messages posted after the join are
emitted
- so a message sent between the invite and the first discovery poll is NOT
swallowed. If no recent join is found (returning session, months-old membership),
the cursor baselines to "now" and nothing historical is emitted (replay guard).
A first-seen DM has no channel_join marker to key off, so it baselines instead to
"now" minus a short window (DM_BASELINE_WINDOW_SECS) - enough that the opening
message that made the DM discoverable isn't swallowed by discovery lag, bounded
so months-old DM history is never replayed.
The baseline applied at first sight is stored alongside the cursor and is from
then on the floor under EVERY cursor in that conversation: no message, top-level
or thread reply, with a ts earlier than it is ever emitted, while a reply posted after it is emitted even when its
thread's parent is older than the baseline. Pre-existing cursor files carry no
stored baseline and are never given one - they fall back to the channel cursor
already on disk, so nothing old is replayed on upgrade. Every cursor file also
carries `sweep_floor_ts` (SKILL.md, the sweep floor). The bot's own messages and
join/system subtypes are skipped.
Requires only stdlib + the token file; no MCP, no Slack SDK.

Who gets delivered:
  Everyone but this bot. A message from another user is delivered whether that
  user is a human or a bot - every post an agent makes through
  `chat.postMessage` carries `bot_id`, and nothing in this file reads that field
  to decide delivery. A bot's line is marked ` [bot]` so a reader can tell an
  agent from a colleague, derived from the message itself and from no config.
  ⚠️ CHANNEL MEMBERSHIP IS THE ONLY CONTROL OVER WHAT REACHES THE SESSION. The
  watcher polls every conversation the bot belongs to, so a bot that is a member
  of a channel a machine feed writes to receives that feed, message for message,
  waking the session on each one. `/invite` subscribes and `/kick` unsubscribes;
  there is no per-sender filter to fall back on. Delivery is not authorization
  either: whether a sender may ASK this agent for anything is the agent's
  charter's call, the same for a bot's UID as for a human's.

Configuration: NOTHING workspace-, deployment- or person-specific is hardcoded
here - workspace/bot IDs, the token path, the owning CLAUDE_CONFIG_DIR, the state
prefix, the poll tunables and the known-user labels all live
in the config SLACK_WATCH_CONFIG names - the ONLY way this script is configured
(the transport's watcher contract), so it is required and an unset variable is
a WATCH-CONFIG exit. Required keys are fatal when absent (naming the key); only
poll.* and slack.* default. Run against a different workspace by pointing
SLACK_WATCH_CONFIG at another copy - no code change. Give it its own
state.prefix so the two watchers' cursors and locks stay independent.
"""
import datetime
import fcntl
import http.client
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

# --- configuration -------------------------------------------------------
# NOTHING workspace-, deployment- or person-specific is hardcoded in this file.
# It all lives in the config SLACK_WATCH_CONFIG names, and the variable is
# REQUIRED: this directory holds the mechanism only, so there is no config beside
# this script to fall back on, and a guessed path would read some other watcher's
# config. Every service that runs the watcher sets the variable.
CONFIG_FILE = os.environ.get("SLACK_WATCH_CONFIG")
_REQUIRED = object()


def _load_config(path: str | None) -> dict:
    if path is None:
        sys.exit("WATCH-CONFIG SLACK_WATCH_CONFIG is not set: point it at this watcher's config "
                 "(the install's own is `fleet where slack-communication config.json`)")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"WATCH-CONFIG missing config file: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"WATCH-CONFIG {path}: not valid JSON - {e}")


CONFIG = _load_config(CONFIG_FILE)


def cfg(dotted: str, default=_REQUIRED):
    """Read a dotted key out of CONFIG.

    A missing REQUIRED key exits loudly naming the key, rather than defaulting.
    Silently defaulting an identity value is how a watcher ends up polling the
    wrong workspace, or answering to an owner that is not the one configured -
    failures that look like "Slack is quiet" rather than like a broken config.
    """
    node = CONFIG
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is _REQUIRED:
                sys.exit(f"WATCH-CONFIG {CONFIG_FILE}: missing required key '{dotted}'")
            return default
        node = node[part]
    return node


def _strip_comments(d: dict) -> dict:
    """Drop the _comment keys config.json uses for documentation (JSON has no
    comment syntax), so they can never be mistaken for data."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


API_BASE = cfg("slack.api_base", default="https://slack.com/api").rstrip("/")
# The workspace this config is FOR. Checked against the token's own team at
# startup (see main) - a config and a token that disagree is a misconfiguration,
# never something to poll through.
TEAM_ID = cfg("workspace.team_id")
WORKSPACE_DOMAIN = cfg("workspace.domain")
BOT_USER = cfg("bot.user_id")
# Display labels only. AUTHORIZATION lives in the agent charter named by the
# config's owner and is enforced per raw UID - every emit line carries the raw
# ID, so an unlabelled sender is still authorized correctly.
KNOWN_USERS = _strip_comments(cfg("known_users", default={}))
# Only this CLAUDE_CONFIG_DIR may run the watcher (enforced in main()).
OWNER_CONFIG_DIR = cfg("owner.claude_config_dir")

POLL_SECS = float(os.environ.get("SLACK_WATCH_POLL_SECS", cfg("poll.poll_secs", default=5)))
# Re-discover channel membership on this cadence (one extra API call).
REDISCOVER_EVERY = max(1, round(float(cfg("poll.rediscover_secs", default=60)) / POLL_SECS))
# On first sight of a channel, look this far back for the bot's own channel_join
# marker. If found, the bot was just invited and messages posted between the
# invite and this first poll are replayed (ts > join). Longer than the rediscovery
# cadence with generous slack; short enough that a returning session with
# months-old membership finds no join and safely baselines to "now".
RECENT_JOIN_WINDOW_SECS = float(
    os.environ.get("SLACK_WATCH_JOIN_WINDOW_SECS", cfg("poll.recent_join_window_secs", default=600))
)
# First sight of a DM: an IM carries NO channel_join marker, so the invite-race
# heuristic above can't apply. A DM only becomes discoverable once its opening
# message is sent, and discovery lags that by up to the rediscovery cadence.
# So baseline a first-seen DM to "now" minus this window and emit deliverable
# messages inside it - the opening message (and anything in the discovery gap) is surfaced,
# while months-old DM history is never replayed. The default 90s = the ~60s
# rediscovery cadence + 30s margin for poll jitter / clock skew.
DM_BASELINE_WINDOW_SECS = float(
    os.environ.get("SLACK_WATCH_DM_WINDOW_SECS", cfg("poll.dm_baseline_window_secs", default=90))
)
# The window, the sweep cadence and the sweep budget: what each governs, and the
# arithmetic the budget's default is sized by, is SKILL.md's "Threads off the
# page, and the sweep" - the one statement of it.
# ⚠️ WINDOW_SECS is a constant, not a config key: it is a delivery promise, and two
# watchers keeping different promises would be one fleet with two contracts.
WINDOW_SECS = 7 * 24 * 3600
SWEEP_SECS = float(os.environ.get("SLACK_WATCH_SWEEP_SECS", cfg("poll.sweep_secs", default=300)))
SWEEP_EVERY = max(1, round(SWEEP_SECS / POLL_SECS))
SWEEP_BUDGET = int(os.environ.get("SLACK_WATCH_SWEEP_BUDGET", cfg("poll.sweep_budget", default=3)))
# The most top-level lines one catch-up delivers per conversation: the newest ones.
CATCHUP_LINES = 200

# ${NAME:-default}, expanded before $NAME and before ~. Kept as its own function
# because NO SINGLE stdlib call does all three: os.path.expandvars knows nothing
# about `:-` or `~`, and os.path.expanduser knows nothing about variables. A
# config naming a secrets store as ${SOME_SECRETS_DIR:-$HOME/.some-secrets} is
# unusable unless all three layers run, in this order.
_DEFAULTED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}]*)\}")
_MAX_EXPANSIONS = 10


def expand_path(raw: str) -> str:
    """Expand ${VAR:-default}, then $VAR / ${VAR}, then a leading ~.

    `or`, not a dict default, implements shell `:-` semantics: an EMPTY variable
    takes the default too, which is what a caller that exported the variable to
    the empty string means.

    An unset variable with NO default is left as the literal `$NAME` by
    expandvars, so the path simply does not exist and every caller reports the
    unexpanded text - which names the variable nobody set. That is the intended
    failure: substituting a guess would silently read the wrong file.
    """
    # BOUNDED, not `while it changes`. The loop repeats only to reach a nested
    # ${A:-${B:-c}}, which is at most a handful of levels; an env var whose own
    # value re-introduces the pattern would otherwise grow the string forever
    # and this function would never return. A hang is the worst failure
    # available here - a watcher that never starts and a check that never
    # answers both look like "still working" - so the loop stops and the
    # remaining text is left literal, which fails loudly instead.
    for _ in range(_MAX_EXPANSIONS):
        prev = raw
        raw = _DEFAULTED.sub(
            lambda m: os.environ.get(m.group(1)) or m.group(2), raw)
        if raw == prev:
            break
    return os.path.expanduser(os.path.expandvars(raw))


# The key file lives OUTSIDE any checkout, so this script anchors nothing to a
# checkout root and needs no worktree special case: every worktree, every clone and
# every cwd resolve the same file. `token.path` carries the whole location.
TOKEN_FILE = expand_path(cfg("token.path"))
# Where the cursors and the lock live. config's state.dir wins; without it they
# fall back to the XDG cache directory.
#
# ⚠️ `or`, NOT os.environ.get's default argument: the default fires only when the
# variable is ABSENT, while the XDG spec says an EMPTY value means unset too. Set
# XDG_CACHE_HOME="" and .get returns "", os.path.join("", name) yields a RELATIVE
# path, and every cursor and the lock land in whatever the working directory
# happens to be - so the watcher re-baselines every conversation to "now" and a
# second watcher started from a different directory takes a different lock and
# runs concurrently, double-emitting. That is the exact failure state.prefix
# exists to prevent, reached without touching the prefix.
_STATE_DIR = cfg("state.dir", "") or os.environ.get("XDG_CACHE_HOME") or "~/.cache"
# expand_path, NOT expanduser: `state.dir` sits in the same config file as
# `token.path`, whose comment advertises ${VAR:-default}, so that is the form an
# author will reach for here too. Under expanduser alone it stays literal, which
# makes it RELATIVE - and a relative CACHE_DIR is precisely the disaster the
# block above describes, reached by a different door.
CACHE_DIR = expand_path(_STATE_DIR)
# ⚠️ config's state.prefix is LIVE ON-DISK STATE, not a name - see its _comment in
# config.example.json before changing it. Two workspaces get two prefixes, which is what
# keeps their cursors and their single-instance locks independent.
STATE_PREFIX = cfg("state.prefix")
# Single-instance lock is channel-independent (one watcher covers all channels).
LOCK_FILE = os.path.join(CACHE_DIR, f"{STATE_PREFIX}.lock")


def state_file(channel_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{STATE_PREFIX}-{channel_id}.json")


class SlackApiError(RuntimeError):
    """A Slack call that answered `{"ok": false, "error": "<code>"}`.

    Carries the error CODE as an attribute so a caller can branch on it without
    parsing it back out of the message. It subclasses RuntimeError and keeps the
    exact `"<method>: <code>"` message the watcher has always printed, so every
    existing `except RuntimeError` and every WATCH-ERROR line is unchanged.

    ⚠️ `.code` exists so `gone_conversation_reason()` never has to re-derive the
    code from `str(exc)`. That parse (an `rsplit(":", 1)` on the message) is
    correct only for as long as the message stays exactly two colon-separated
    fields - and it fails SILENTLY IN BOTH DIRECTIONS the moment it does not: a
    real gone-code stops matching and the flood returns, or an unrelated message
    tail starts matching and a LIVE conversation is retired. Nothing reds;
    appending one detail to the message below is all it takes. If you
    add fields to this message, `.code` is why you do not have to think about it.
    """

    def __init__(self, method: str, code: str):
        super().__init__(f"{method}: {code}")
        self.method = method
        self.code = code


# How many times a single Slack call may be ISSUED before its read failure is
# allowed out. 3 = the first try plus two retries.
#
# ⚠️ WHAT THIS IS FOR, AND WHAT BREAKS IF THE RETRY IS REMOVED. A large
# `conversations.history` body (a DM full of image messages is ~260 KB) can be
# cut mid-body by the far side closing the connection cleanly, which surfaces as
# `http.client.IncompleteRead(<n> bytes read, <m> more expected)` where n+m is
# the Content-Length. Measured: the cut lands at ~66,316 bytes = the client's
# ~64 KiB TCP receive window, i.e. it is the amount of data in flight and NOT a
# property of the body, which is why the same offset recurs across unrelated
# response sizes. It is a link-level event, so it is NOT reproducible on demand
# from a healthy link - `watch.test.py` §16 is the only repeatable measurement
# of this code path and the reason it is written against a fake response object
# rather than the network.
# Without the retry every hit costs one per-poll WATCH-ERROR line and that
# conversation's poll: `poll_channel()` raises before `save_state()`, so no
# message is lost, but delivery waits a full POLL_SECS and the operator reads a
# real error for a condition that clears on the next request (measured: a
# direct re-fetch of the same URL returns the whole body in ~1.3 s).
#
# ⚠️ WHY THE RETRY WRAPS ONLY THE READ. The `ok:false` check is deliberately
# OUTSIDE the loop. A Slack-level error is an ANSWER, not a failed read -
# re-issuing it would triple the request rate on exactly the conditions
# (`ratelimited`) where that is worst, and would triple the probe count that
# section 15's retirement guard counts. `watch.test.py` §16c pins that.
#
# ⚠️ WHY THE LAST ERROR IS RE-RAISED UNCHANGED. A persistent fault must still
# reach the per-conversation WATCH-ERROR guard in `main()` as its original
# exception class. Swallowing it here - returning `{}`, or an empty message list
# - would make a broken read indistinguishable from a quiet conversation, which
# is the ALIVE AND SILENT state described below and the worst one the watcher
# has. `watch.test.py` §16b pins that.
_READ_ATTEMPTS = 3
# The read failures that are worth re-issuing: a clean peer FIN mid-body, a
# reset, and a read that outran the timeout. `socket.timeout` is an alias of
# `TimeoutError` on python >= 3.10, which watch.test.py already requires.
_RETRYABLE_READ_ERRORS = (http.client.IncompleteRead, ConnectionResetError, TimeoutError)


def api(method: str, **params) -> dict:
    with open(TOKEN_FILE) as f:
        token = f.read().strip()
    url = f"{API_BASE}/{method}?" + urllib.parse.urlencode(params)
    for attempt in range(_READ_ATTEMPTS):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                # Read the body, then parse. `IncompleteRead.partial` is
                # deliberately dropped: a truncated body is truncated JSON.
                body = resp.read()
            break
        except _RETRYABLE_READ_ERRORS:
            if attempt == _READ_ATTEMPTS - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    data = json.loads(body)
    if not data.get("ok"):
        raise SlackApiError(method, str(data.get("error")))
    return data


# Slack error codes that mean "this conversation is GONE, and DISCOVERY WILL NOT
# NOTICE", as opposed to "this call failed". A conversation that answers one of
# these answers it again on the next poll, and on every poll after that, forever
# - so the per-conversation WATCH-ERROR guard in main(), which exists to keep ONE
# bad conversation from killing the whole watch, turns a permanent condition into
# one line every POLL_SECS. Measured consequence, and the reason this set exists:
# a DM to a deactivated/Slackbot-style user stays in `users.conversations`
# discovery while `conversations.history` on it answers `channel_not_found` for a
# bot token, permanently - ~720 lines an hour at the default 5s poll, each one a
# Monitor wake-up event, until Monitor's own rate limiter stops the monitor
# outright. The watcher is then ALIVE AND SILENT, which is the worst state it
# has: nothing errors, nothing arrives, and the operator's only evidence is an
# absence.
#
# ⚠️ WHAT BREAKS IF THIS SET IS WIDENED. Retirement means this process stops
# polling that conversation and says nothing further about it, until the watcher
# restarts. That is correct ONLY where no retry AND NO REDISCOVERY can clear the
# condition. Everything not named here deliberately keeps the per-poll
# WATCH-ERROR: for a fault that can end, repetition IS the signal that it has not
# ended yet.
#
# ⚠️ THE MEMBERSHIP TEST IS "DOES DISCOVERY ALREADY FIX THIS?", NOT "IS THIS
# ERROR PERMANENT?" - and that is why `not_in_channel` and `is_archived` are NOT
# members, though both READ as permanent and both were in the first draft of this
# set. Discovery is itself the self-healing mechanism for them:
#   not_in_channel - the bot was kicked. `discover_channels` calls
#                    `users.conversations`, which lists only conversations the
#                    caller BELONGS TO, so the next rediscovery drops the channel
#                    from the watched set on its own.
#   is_archived    - both discovery calls pass `exclude_archived=true`, so the
#                    next rediscovery drops it on its own.
# For either, retiring buys only the lines between the event and the next
# rediscovery - at the defaults, 60s/5s = 12 polls, i.e. ~12 WATCH-ERROR lines,
# once, which is a normal transient and not a flood. What it RISKS is the whole
# failure this guard is supposed to prevent, pointed the other way: if such an
# error ever arrives transiently - a freshly `/invite`d channel whose membership
# is visible to `users.conversations` before the read path agrees, so poll #1
# answers `not_in_channel` - the channel is retired on its first ever poll and
# stays retired, because the bot IS a member, so it never leaves discovery and
# the prune in main() never clears it. A live channel then goes dark for the rest
# of the process behind ONE line, and that line is easy to miss precisely because
# it is not a flood. Trading ~12 transient lines for that is a bad trade in both
# directions at once, so the set holds the ONE code where discovery is proven not
# to help: `channel_not_found` on a conversation discovery keeps returning is
# self-contradictory and, measured, permanent. That contradiction IS the
# membership test.
#
# Provenance, against Slack's own reference (fetched 2026-09-12,
# docs.slack.dev/reference/methods/{conversations.history,conversations.replies}):
# `channel_not_found` is documented on BOTH read methods, and is the observed
# case. Also deliberately absent, each a permanent-LOOKING read failure that
# discovery does not clear: `channel_is_limited_access` and
# `method_not_supported_for_channel_type` are documented but have never been
# observed here, and an unobserved permanent condition is better read as a loud
# unknown than silently retired. Transient codes (`ratelimited`,
# `service_unavailable`, `internal_error`) and install-scoped ones
# (`missing_scope`, `token_revoked`, `account_inactive`) are not members for the
# original reason: the first recovers by itself, and the second is fixed by a
# human who has to SEE it repeat.
#
# ⚠️ THERE IS NO DEBOUNCE, AND THAT IS A CHOICE. One poll answering
# `channel_not_found` retires the conversation; requiring N consecutive failures
# would cost one dict and one extra poll of latency, and would additionally
# protect against a single-poll race on THIS code too. It is not here because no
# such race has been observed for `channel_not_found` and the narrowing above
# already removes the two codes whose races are motivated - so a debounce would
# be complexity bought against a hazard nobody has measured. What is forgone:
# if `channel_not_found` ever DOES arrive transiently, this retires on the first
# one. That is the failure to look for if a live conversation ever goes quiet
# with a single WATCH-INFO line and no other explanation.
GONE_CONVERSATION_ERRORS = frozenset({
    "channel_not_found",
})


def gone_conversation_reason(exc: BaseException) -> str | None:
    """The Slack error code, if `exc` says this conversation is gone (see above).

    None for everything else, including every exception that is not a
    `SlackApiError`: only a Slack `{"ok": false}` answer carries an error code at
    all, and a urllib/socket failure is transient by nature. The code is read off
    the exception ATTRIBUTE rather than parsed out of its message - see
    `SlackApiError` for why that distinction is load-bearing - and compared
    EXACTLY, never by substring: a substring test would retire a conversation on
    any code that merely CONTAINS one of these, and the cost of a false
    retirement is permanent silence on a live conversation.
    """
    if not isinstance(exc, SlackApiError):
        return None
    return exc.code if exc.code in GONE_CONVERSATION_ERRORS else None


def discover_channels(warn_state: dict | None = None) -> dict:
    """Return {channel_id: channel_name} for every PUBLIC or PRIVATE channel the
    bot is a member of. `users.conversations` only lists conversations the caller
    belongs to, so membership == subscription - and one call with
    `types=public_channel,private_channel` returns BOTH (the bot has groups:read,
    verified 2026-07-21), so `/invite`-ing the bot to a private channel subscribes
    it exactly like a public one. Private channels emit identically to public ones
    (`SLACK #<name> ...`) - they still have a name. DMs are discovered separately by
    `discover_dms`. Paginated to be safe though the fleet has a handful of channels.

    Defensive missing_scope grace: private channels need groups:read. That scope is
    present today, so the combined-types call succeeds; but if it ever loses the
    private scope, Slack answers `missing_scope`. Rather than lose ALL channels we
    degrade to public-only: log ONE stderr line (latched via `warn_state` so the
    ~60s rediscovery loop doesn't spam it) and retry the call with `public_channel`.
    Combined types is re-probed every rediscovery cycle, so private channels light
    back up automatically if the scope returns. The latch is re-armed only on a
    successful FULL (private-included) probe, so a persistent scope loss logs once,
    not once per cycle (mirrors `discover_dms`)."""
    types = "public_channel,private_channel"
    while True:
        channels: dict[str, str] = {}
        try:
            for page, _next in _pages("users.conversations", "channels",
                                      {"types": types, "exclude_archived": "true"}):
                if warn_state is not None and "private_channel" in types:
                    warn_state["logged"] = False  # full scope worked - re-arm the one-shot warn
                channels.update((c["id"], c.get("name", c["id"])) for c in page)
            return channels
        except RuntimeError as e:
            if "missing_scope" not in str(e) or "private_channel" not in types:
                raise
            if warn_state is not None and not warn_state.get("logged"):
                print("WATCH-INFO groups scope not granted (groups:read) - "
                      "private channels invisible; polling public channels only; "
                      "re-probing combined types each rediscovery",
                      file=sys.stderr, flush=True)
            if warn_state is not None:
                warn_state["logged"] = True
            types = "public_channel"  # fall back and retry from scratch


def discover_dms(warn_state: dict) -> dict:
    """Return {dm_id: partner_uid} for every open IM conversation with the bot.

    DMs are polled via the same `users.conversations` endpoint with `types=im`,
    which requires the `im:read` scope (`im:history` to then read them). If the
    install lacks those scopes (reinstall pending) Slack answers the probe with
    `missing_scope`: we log ONE stderr line (latched via `warn_state` so a
    ~60s-cadence rediscovery loop doesn't spam it), return {} so the caller keeps
    polling channels only, and - because discovery re-runs every cycle - re-probe
    automatically, lighting DMs up the moment the scopes are granted, no restart.
    `warn_state["logged"]` is cleared on a successful probe so a later scope loss
    would log once again. Any non-scope error propagates to the caller's guard."""
    dms: dict[str, str] = {}
    try:
        for page, _next in _pages("users.conversations", "channels",
                                  {"types": "im", "exclude_archived": "true"}):
            warn_state["logged"] = False  # scopes present now - re-arm the one-shot warn
            dms.update((c["id"], c.get("user", c["id"])) for c in page)
    except RuntimeError as e:
        if "missing_scope" not in str(e):
            raise
        if not warn_state.get("logged"):
            print("WATCH-INFO im scopes not granted yet "
                  "(im:read/im:history) - DMs invisible until the bot is "
                  "reinstalled; re-probing each rediscovery",
                  file=sys.stderr, flush=True)
            warn_state["logged"] = True
        return {}
    return dms


def is_deliverable(msg: dict) -> bool:
    """Should this message be printed into the owning agent's session?

    Named for the decision it makes, not for who sends it: it delivers humans
    AND bots, so a name like `is_human` would be a lie the next reader has to
    discover by reading the body.

    Three conditions, and every message that clears them is delivered - the
    sender being a bot is not one of them, and must not become one:

    - `user` is present. A message with no user id is a classic webhook/app post
      and there is nobody to authorize it against - the emit line's whole job is
      to carry a UID the agent's charter can check.
    - `user` is not this bot. Without it the watcher reads its own posts back
      into its session: not just noise, but a feedback loop that spends the poll
      budget and, at this watcher's rate limit, goes deaf.
    - `subtype` is None. Joins, leaves, topic changes and the rest are events,
      not correspondence.

    ⚠️ `bot_id` IS NOT CONSULTED, AND RE-ADDING IT IS A REGRESSION. Every post a
    fleet agent makes through `chat.postMessage` carries `bot_id` with `user`
    set to that agent's own user id, so a `not msg.get("bot_id")` clause here
    makes two fleet agents invisible to each other even when one @-mentions the
    other - a silent one, because nothing fails and there is no line to read.
    "Filter out the bot noise" is how that clause gets reintroduced.

    ⚠️ WHAT REACHES THE SESSION IS DECIDED BY CHANNEL MEMBERSHIP, NOWHERE ELSE.
    A machine feed - a product bot posting one message per completed job - is
    delivered message for message in any channel this bot belongs to. `/invite`
    is the subscription and `/kick` the unsubscription; keeping the bot out of
    such a channel is the whole of the control, and there is no sender filter
    underneath it to catch a mistaken invite.

    A message being DELIVERED says nothing about it being a REQUEST. Whether a
    given sender may ask this agent for anything is the agent's charter's call,
    the same for a bot's UID as for a human's.
    """
    uid = msg.get("user")
    return uid is not None and uid != BOT_USER and msg.get("subtype") is None


def label(msg: dict) -> str:
    """The sender part of an emit line: `Name (UID)`, or the bare UID unlabelled.

    A bot is labelled from `known_users` exactly as a person is, and then marked
    ` [bot]`. The marker is not decoration: a line from another agent and a line
    from a colleague authorize different things, and without it the only way to
    tell them apart is to have memorised which UIDs are bots.

    ⚠️ The marker is derived from THIS MESSAGE's `bot_id` and from no config, so
    it cannot disagree with reality: there is no list to fall out of step with
    the workspace, and a sender wrongly recorded somewhere as a bot or a person
    cannot make the line lie. Every real fleet bot's post carries `bot_id`
    (measured 2026-09-04 against live `conversations.history`); a human's never
    does.
    """
    uid = msg.get("user", "?")
    name = KNOWN_USERS.get(uid)
    marker = " [bot]" if msg.get("bot_id") else ""
    return f"{name}{marker} ({uid})" if name else f"{uid}{marker}"


def emit(msg: dict, channel_name: str | None, parent_ts: str | None = None,
         is_dm: bool = False) -> None:
    where = f"reply in thread {parent_ts}" if parent_ts else "message"
    text = " ".join((msg.get("text") or "").split())[:500]
    # A DM has no channel name - mark it "DM" so the session's triage can tell a
    # direct message from a channel post at a glance.
    prefix = "DM" if is_dm else f"#{channel_name}"
    print(f"SLACK {prefix} {where} [ts {msg['ts']}] {label(msg)}: {text}", flush=True)


def load_state(channel_id: str) -> dict:
    try:
        with open(state_file(channel_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(channel_id: str, state: dict) -> None:
    path = state_file(channel_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def own_join_ts(messages: list) -> str | None:
    """The ts of the bot's OWN most recent `channel_join` in `messages`, or None.

    The most recent one, because a re-invited bot has several: an older join
    would baseline the channel before a period the bot was NOT a member of, and
    everything posted in that period would replay as if live."""
    join_ts = None
    for m in messages:
        if m.get("subtype") == "channel_join" and m.get("user") == BOT_USER:
            ts = m.get("ts")
            if ts is not None and (join_ts is None or float(ts) > float(join_ts)):
                join_ts = ts
    return join_ts


def initial_baseline(messages: list, now: float) -> tuple[str, list]:
    """Decide the initial cursor for a channel seen for the first time.

    `messages` is the recent history slice (any order); `now` is the fallback
    baseline. If the bot's OWN channel_join marker is present, the bot was just
    invited: baseline to the join ts and return the deliverable messages posted
    after it (ascending) so nothing sent between invite and first poll is swallowed.
    Otherwise (no recent join - a returning session / old membership) baseline to
    `now` and emit nothing, preserving the no-replay guard. Pure: no I/O, so the
    decision is unit-testable against recorded API responses."""
    join_ts = own_join_ts(messages)
    if join_ts is None:
        return f"{now:.6f}", []
    to_emit = [
        m for m in sorted(messages, key=lambda m: float(m["ts"]))
        if float(m["ts"]) > float(join_ts) and is_deliverable(m)
    ]
    baseline = to_emit[-1]["ts"] if to_emit else join_ts
    return baseline, to_emit


def dm_initial_baseline(messages: list, window_ts: str) -> tuple[str, list]:
    """Decide the initial cursor for a DM seen for the first time.

    An IM has no channel_join marker, so (unlike `initial_baseline`) there is no
    invite signal to key off. `window_ts` is "now" minus DM_BASELINE_WINDOW_SECS:
    replay the deliverable messages after it (ascending) - the opening message that made
    the DM discoverable, plus anything in the discovery gap - and baseline the
    cursor to the newest replayed message (or `window_ts` if none). The window is
    bounded, so months-old DM history is never replayed. Pure: no I/O, so the
    decision is unit-testable against recorded API responses."""
    to_emit = [
        m for m in sorted(messages, key=lambda m: float(m["ts"]))
        if float(m["ts"]) > float(window_ts) and is_deliverable(m)
    ]
    baseline = to_emit[-1]["ts"] if to_emit else window_ts
    return baseline, to_emit


def _pages(method: str, key: str, params: dict, cursor: str = ""):
    """Yield (items, next_cursor) for each page of a cursor-paginated Web API
    method - `items` is the answer's `key` list - 200 a page, starting at
    `cursor` and following `next_cursor` until Slack says there is no more.
    Nothing is fetched ahead, so a caller that stops iterating resumes later
    from the last cursor it was handed."""
    while True:
        call = {**params, "limit": 200}
        if cursor:
            call["cursor"] = cursor
        data = api(method, **call)
        cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
        yield data.get(key, []), cursor
        if not cursor:
            return


def _recent_window_messages(channel_id: str, oldest: str, max_pages: int = 5) -> list:
    """Paginate conversations.history within the recent window until the bot's own
    channel_join is found or the window is exhausted. A call bounded by `oldest`
    alone returns the oldest messages after it first (measured 2026-11-04), so
    the join usually sits on page 1 - but in a busy window it can sit past the
    first 200 messages, and stopping at page 1 there would resurface the very
    swallow this fix targets, so every page of the window is read until the join
    is found, with a hard page cap as a runaway backstop."""
    messages: list = []
    pages = _pages("conversations.history", "messages", {"channel": channel_id, "oldest": oldest})
    for n, (page, _next) in enumerate(pages):
        messages.extend(page)
        if any(m.get("subtype") == "channel_join" and m.get("user") == BOT_USER for m in page):
            break  # join found - older pages are before the invite, irrelevant
        if n + 1 >= max_pages:
            break
    return messages


def _spend(budget: dict | None) -> bool:
    """Take one call from a sweep budget (`run_sweep`); False, taking nothing,
    when it is spent. None is no budget at all (`--once`)."""
    if budget is None:
        return True
    if budget["left"] <= 0:
        return False
    budget["left"] -= 1
    return True


def _where(conversation_id: str, name: str | None, is_dm: bool, with_id: bool = False) -> str:
    """How a line names a conversation: `DM <id>`, `#<name>`, or `#<name> (<id>)`."""
    if is_dm:
        return f"DM {conversation_id}"
    return f"#{name} ({conversation_id})" if with_id else f"#{name}"


def _read_thread(channel_id: str, channel_name: str | None, state: dict, parent_ts: str,
                 latest_reply: str | None, floor: str, is_dm: bool,
                 off_page: bool = False, budget: dict | None = None) -> bool:
    """Emit the unread replies of one thread and advance its cursor. Returns
    False, having made no call, when `budget` is spent.

    Reading starts at the thread's own cursor, or for a thread with none at the
    LATER of its parent ts and `floor` - which is what makes "nothing older than
    the floor is ever emitted" hold for replies too. On the poll's page `floor`
    is the first-sight baseline and a stored cursor wins outright; off it
    (`off_page`) `floor` is the sweep floor and bounds a stored cursor too
    (SKILL.md, the sweep floor). `latest_reply` is None when the caller has no
    parent in hand (one older than the window): then the call is made anyway and
    the parent's field is read off the answer.

    ⚠️ The cursor is the newest reply THIS call read, never history's
    `latest_reply` alone: the replies call runs after the history call and can
    hold newer replies of the same burst, which were just emitted - a cursor
    behind them emits them again. With `has_more`, the cursor stops at the newest
    reply read (the call returns the earliest replies after `oldest` first) - as
    long as the page moved it at all: a `has_more` page with nothing past the
    cursor falls through to the `latest_reply` rule, or the thread costs a call
    every poll for good. Without `has_more`, the `latest_reply` term advances
    past a reply history names that the call did not return (deleted, or not yet
    visible), for the same reason. watch.test.py §10x.
    ⚠️ A cursor is only ever written FORWARD of where reading started, so it
    always names a real reply: written back at a floor, a quiet thread would look
    active and stay inside the window longer than its replies do.
    """
    seen = state["threads"].get(parent_ts) or max(parent_ts, floor, key=float)
    if off_page:
        seen = max(seen, floor, key=float)
    if latest_reply is not None and float(latest_reply) <= float(seen):
        return True
    if not _spend(budget):
        return False
    replies = api("conversations.replies", channel=channel_id, ts=parent_ts, oldest=seen, limit=50)
    messages = replies.get("messages", [])
    newest_read = seen
    for r in sorted(messages, key=lambda m: float(m["ts"])):
        if float(r["ts"]) > float(seen) and r["ts"] != parent_ts:
            newest_read = r["ts"]
            if is_deliverable(r):
                emit(r, channel_name, parent_ts=parent_ts, is_dm=is_dm)
    if latest_reply is None:
        parent = next((m for m in messages if m.get("ts") == parent_ts), {})
        latest_reply = parent.get("latest_reply") or newest_read
    if replies.get("has_more") and newest_read != seen:
        cursor = newest_read
    else:
        cursor = max(latest_reply, newest_read, key=float)
    if float(cursor) > float(seen):
        state["threads"][parent_ts] = cursor
    return True


def _iso(ts: str) -> str:
    return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _catch_up(channel_id: str, channel_name: str | None, state: dict, start: str,
              is_dm: bool, capped: bool):
    """The catch-up (SKILL.md): the poll's page does not reach the cursor. Returns
    (messages to process, edge for the sweep). It keeps the newest CATCHUP_LINES
    top-level messages from `start` on - `start` itself included, so a parent
    whose replies call failed after the cursor reached it is read again
    (delivery is cursor-gated: nothing repeats).
    ⚠️ It asks for ONE more than it keeps: the extra message, the newest one not
    kept, is what says whether anything after the cursor was skipped. `has_more`
    cannot - an unbounded call sets it whenever older history exists at all, so
    a backlog of exactly CATCHUP_LINES would announce a skip that never happened.
    When something is skipped, ONE WATCH-INFO line says so, before the delivery
    it precedes, and the sweep floor rises to the oldest message kept, so the
    replies under the skipped parents are bounded by the same cap; never lowered.
    Nothing is counted: a count costs a call per 200 skipped, in one poll."""
    hist = api("conversations.history", channel=channel_id, limit=CATCHUP_LINES + 1)
    got = sorted(hist.get("messages", []), key=lambda m: -float(m["ts"]))
    newest, beyond = got[:CATCHUP_LINES], got[CATCHUP_LINES:]
    kept = [m for m in newest if float(m["ts"]) >= float(start)]
    edge, note = start, []
    if kept and beyond and float(beyond[0]["ts"]) > float(start):
        edge = kept[-1]["ts"]
        state["sweep_floor_ts"] = max(state["sweep_floor_ts"], edge, key=float)
        note.append(f"delivered the newest {len(kept)} top-level messages; messages and thread "
                    f"replies posted from {_iso(start)} to before {_iso(edge)} were not delivered")
    if capped:
        note.append(f"cursor {_iso(state['channel_ts'])} is older than the "
                    f"{WINDOW_SECS / 86400:g}-day window - top-level messages posted before "
                    f"{_iso(start)} were not read")
    if note:
        print(f"WATCH-INFO {_where(channel_id, channel_name, is_dm, with_id=True)}: catch-up "
              f"{'; '.join(note)} - read them on demand with the slack-communication skill's "
              f"'Fetch a message / thread' recipe", file=sys.stderr, flush=True)
    if got and not kept:
        # ⚠️ Nothing inside the window: the cursor goes to the newest message, so the
        # next poll's page reaches it. Left alone, every poll would repeat this
        # catch-up and its WATCH-INFO line - a per-poll flood. Not to `start`, which
        # moves with the clock.
        state["channel_ts"] = max(state["channel_ts"], got[0]["ts"], key=float)
    return kept, edge


def poll_channel(channel_id: str, channel_name: str | None, state: dict,
                 is_dm: bool = False) -> str | None:
    """One poll of one conversation: emit what is new since its cursors, and
    return the EDGE for the sweep - the ts below which this poll read nothing
    although history continues there. None when nothing is off the page: the
    page reached the conversation's start, or it was first sight."""
    # First ever sight of this conversation. Fetch a short recent window and
    # baseline: for a channel, look for the bot's own join (invite-race replay);
    # for a DM (no join marker) baseline to now - DM_BASELINE_WINDOW_SECS and
    # replay the deliverable messages inside it. Do the API call BEFORE mutating state,
    # so a transient failure leaves state empty for a clean retry.
    # THREAD replies are not in this top-level slice, and first-sight sets
    # threads={}, so `baseline_ts` is what keeps the next normal poll from
    # reaching back past the baseline: it is the FLOOR under every cursor,
    # top-level and thread alike. Without it a cursorless thread defaults to its
    # own parent ts, and since the normal poll's top-level page reaches
    # arbitrarily far back in a quiet conversation, every reply of every visible
    # thread replays as if live. `channel_ts` cannot serve as that floor: it
    # advances to the newest message emitted here, so a reply posted between the
    # join and that message would be swallowed - the invite race, one layer down.
    if not state:
        if is_dm:
            # ⚠️ A DM's floor bounds its THREAD replies too, and this bot's DMs
            # are assistant-threaded, so a human's message IS a thread reply. On
            # a genuine first sight that is what the window is for: the message
            # that made the DM discoverable is inside it. When a DM cursor file
            # is missing for any OTHER reason (the state prefix changed, the
            # cache was wiped), a human reply older than the window is dropped
            # rather than surfaced - the same trade the window already made for
            # top-level DM messages, now applied consistently. The alternative
            # is replaying the whole DM conversation, which in a DM means
            # answering messages that were answered weeks ago.
            floor = f"{time.time() - DM_BASELINE_WINDOW_SECS:.6f}"
            hist = api("conversations.history", channel=channel_id, oldest=floor, limit=200)
            baseline, to_emit = dm_initial_baseline(hist.get("messages", []), floor)
        else:
            now = time.time()
            oldest = f"{now - RECENT_JOIN_WINDOW_SECS:.6f}"
            messages = _recent_window_messages(channel_id, oldest)
            baseline, to_emit = initial_baseline(messages, now)
            # The same decision initial_baseline made, kept as the floor: the
            # bot's own join when it was just invited, otherwise "now".
            floor = own_join_ts(messages) or f"{now:.6f}"
        for msg in to_emit:
            emit(msg, channel_name, is_dm=is_dm)
        state["channel_ts"] = baseline
        state["baseline_ts"] = floor
        state["sweep_floor_ts"] = floor
        state["threads"] = {}
        return None
    if not state.get("sweep_floor_ts"):
        # ⚠️ "Now", never the cursor or the baseline: either would deliver, days
        # late and at once, the off-page replies a watcher that does not sweep
        # left unread (SKILL.md, the sweep floor).
        state["sweep_floor_ts"] = f"{time.time():.6f}"
    edge = None
    hist = api("conversations.history", channel=channel_id, limit=50)
    messages = hist.get("messages", [])
    if hist.get("has_more") and messages:
        edge = min((m["ts"] for m in messages), key=float)
        if float(edge) > float(state["channel_ts"]):
            # The page does not reach the cursor: catch up.
            window_start = time.time() - WINDOW_SECS
            capped = float(state["channel_ts"]) < window_start
            start = f"{window_start:.6f}" if capped else state["channel_ts"]
            messages, edge = _catch_up(channel_id, channel_name, state, start, is_dm, capped)
    # A state file written before `baseline_ts` existed falls back to the cursor
    # already on disk, and is never given one - no replay on upgrade: the
    # fallback can only suppress MORE than a floor-less poll did.
    # `or`, not a dict default, so a hand-edited `"baseline_ts": null` degrades
    # to the cursor instead of raising inside float() - which main() would turn
    # into one WATCH-ERROR per poll, leaving that conversation permanently
    # silent while the watcher looks healthy.
    # ⚠️ Known cost: a legacy file's floor is `channel_ts`, re-read every poll,
    # so it RATCHETS upward with the cursor and a reply older than the cursor in
    # a cursorless thread on the page is skipped. The sweep floor is NOT a
    # drop-in fix: frozen at the upgrade, on the page it would suppress replies
    # the ratchet still delivers (posted before the upgrade, after the cursor).
    floor = state.get("baseline_ts") or state["channel_ts"]
    for msg in sorted(messages, key=lambda m: float(m["ts"])):
        if float(msg["ts"]) > float(state["channel_ts"]):
            if is_deliverable(msg):
                emit(msg, channel_name, is_dm=is_dm)
            # ⚠️ The cursor moves with EVERY message, not once at the end: main()
            # keeps and saves this same dict when a later call in the poll raises,
            # and a cursor that had not moved would deliver everything above this
            # line again. watch.test.py §10y-ix.
            state["channel_ts"] = msg["ts"]
        # Thread with new activity? Fetch only the unseen tail.
        if msg.get("reply_count"):
            _read_thread(channel_id, channel_name, state, msg["ts"],
                         msg.get("latest_reply", "0"), floor, is_dm)
    return edge


def sweep_due(conversation_id: str, poll_count: int) -> bool:
    """Is poll `poll_count` the one that starts a sweep of `conversation_id`?
    Once every SWEEP_EVERY polls, at a phase derived from the id, so a fleet of
    conversations does not sweep on the same poll. crc32 rather than hash():
    hash() of a str is salted per process, and a phase nobody can reproduce
    cannot be tested."""
    return (poll_count + zlib.crc32(conversation_id.encode())) % SWEEP_EVERY == 0


def new_sweep(edge: str | None) -> dict | None:
    """The position of a sweep starting now at the poll's `edge`, or None when
    nothing is off the page. Process-scoped and never saved: a restarted sweep
    re-reads history pages, never replies, because the thread cursors it advanced
    are on disk."""
    if edge is None:
        return None
    return {"edge": edge, "window_start": f"{time.time() - WINDOW_SECS:.6f}",
            "cursor": "", "pages_done": False, "pending": [], "old_after": None}


# Slack error codes about ONE thread rather than the conversation or the service:
# the sweep goes on past that thread (`_sweep_thread`). Anything else stops it.
THREAD_GONE_ERRORS = frozenset({"thread_not_found"})
# (conversation, parent ts) of history-pass threads already reported gone.
_REPORTED_GONE: set = set()


def is_rate_limit(exc: BaseException) -> bool:
    """Is `exc` Slack refusing for rate? Two forms: HTTP 429, which urlopen
    raises as HTTPError before any body is read, and `{"error": "ratelimited"}`."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429
    return isinstance(exc, SlackApiError) and exc.code == "ratelimited"


def _sweep_thread(channel_id: str, channel_name: str | None, state: dict, parent_ts: str,
                  latest_reply: str | None, is_dm: bool, budget: dict | None) -> bool:
    """One off-page thread read; False when `budget` is spent. A thread Slack
    says is gone (THREAD_GONE_ERRORS) does not stop the sweep, so it cannot hide
    the threads after it; every other error is raised and stops the sweep.
    ⚠️ Only the old-parent pass (`latest_reply` None) forgets the thread: nothing
    else would ever list it again. A thread from the history pass keeps its
    cursor and is reported once per process - its parent is still listed, so
    forgetting it would repeat the line every sweep, and on an answer that
    turned out transient would read it again from the floor and re-send replies
    already delivered."""
    try:
        return _read_thread(channel_id, channel_name, state, parent_ts, latest_reply,
                            state["sweep_floor_ts"], is_dm, off_page=True, budget=budget)
    except SlackApiError as e:
        if e.code not in THREAD_GONE_ERRORS:
            raise
        where = _where(channel_id, channel_name, is_dm, with_id=True)
        if latest_reply is None:
            state["threads"].pop(parent_ts, None)
            print(f"WATCH-INFO {where}: thread {parent_ts} is gone (Slack says {e.code}) - "
                  f"no longer read", file=sys.stderr, flush=True)
        elif (channel_id, parent_ts) not in _REPORTED_GONE:
            _REPORTED_GONE.add((channel_id, parent_ts))
            print(f"WATCH-INFO {where}: thread {parent_ts} answers {e.code} - skipped, its "
                  f"cursor kept; not reported again by this process", file=sys.stderr, flush=True)
        return True


def sweep_channel(channel_id: str, channel_name: str | None, state: dict, pos: dict,
                  is_dm: bool = False, budget: dict | None = None) -> bool:
    """Advance the sweep at `pos` (from `new_sweep`): True when it is complete,
    False when `budget` ran out first, `pos` then holding where to resume.
    What it reads and why: SKILL.md, the sweep. ⚠️ `pos` is updated as each
    thread and page is finished, never ahead of the work, so a sweep that raises
    part-way resumes after the last thing it finished and reads nothing twice."""
    while True:
        while pos["pending"]:
            parent_ts, latest_reply = pos["pending"][0]
            if not _sweep_thread(channel_id, channel_name, state, parent_ts, latest_reply,
                                 is_dm, budget):
                return False
            pos["pending"].pop(0)
        if pos["pages_done"] or float(pos["edge"]) <= float(pos["window_start"]):
            break
        if not _spend(budget):
            return False
        page, pos["cursor"] = next(_pages(
            "conversations.history", "messages",
            {"channel": channel_id, "latest": pos["edge"], "oldest": pos["window_start"]},
            pos["cursor"]))
        pos["pending"] = [(m["ts"], m.get("latest_reply", "0")) for m in page if m.get("reply_count")]
        pos["pages_done"] = not pos["cursor"]
    reach = min(float(pos["edge"]), float(pos["window_start"]))
    for parent_ts, cursor in sorted(state["threads"].items(), key=lambda kv: float(kv[0])):
        if pos["old_after"] is not None and float(parent_ts) <= float(pos["old_after"]):
            continue
        if float(parent_ts) < reach and float(cursor) >= float(pos["window_start"]):
            if not _sweep_thread(channel_id, channel_name, state, parent_ts, None, is_dm, budget):
                return False
        pos["old_after"] = parent_ts
    return True


def run_sweep(conversation_id: str, name: str | None, state: dict, edge: str | None,
              sweeps: dict, budget: dict | None, is_dm: bool = False) -> None:
    """Start or continue one conversation's sweep, isolated from its poll.
    `sweeps` holds every sweep in progress; `budget` is this poll's, shared by
    every conversation. The error policy is SKILL.md's (the sweep): one line, no
    retirement, and the position kept only after a rate limit."""
    pos = sweeps.get(conversation_id) or new_sweep(edge)
    if pos is None:
        return
    sweeps[conversation_id] = pos
    try:
        try:
            done = sweep_channel(conversation_id, name, state, pos, is_dm=is_dm, budget=budget)
        finally:
            save_state(conversation_id, state)
        if done:
            sweeps.pop(conversation_id, None)
    except Exception as e:  # one sweep must not cost the conversation's poll
        if not is_rate_limit(e):
            sweeps.pop(conversation_id, None)
        print(f"WATCH-ERROR sweep {_where(conversation_id, name, is_dm)} {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)


def acquire_singleton_lock():
    """Slack-agent-only + single-instance guards (both exit 0 so a Monitor just ends).

    Only the agent whose CLAUDE_CONFIG_DIR matches config's owner.claude_config_dir
    owns the watch: every other agent refuses here, so all services can share the
    same arm-at-session-start rule without double-processing. The flock catches
    everything else (a leftover watcher from a crashed session, a concurrent
    manual run). One lock covers all channels - a single watcher process handles
    every discovered channel. Returns the held lock fd; keep it referenced for
    process lifetime.
    """
    caller_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    owner = os.path.realpath(os.path.expanduser(OWNER_CONFIG_DIR))
    if not caller_dir or os.path.realpath(caller_dir) != owner:
        print(
            f"WATCH-GUARD not the owning agent "
            f"(CLAUDE_CONFIG_DIR={caller_dir or '<unset>'}, owner={OWNER_CONFIG_DIR}); not watching",
            file=sys.stderr, flush=True,
        )
        sys.exit(0)
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("WATCH-GUARD another watcher already holds the lock; not watching", file=sys.stderr, flush=True)
        sys.exit(0)
    return fd


def assert_token_readable() -> None:
    """Stop on a token file that cannot be read, with a WATCH-CONFIG line naming the
    key and the path, before the first Slack call. Left to api(), its open() raises
    a traceback, which under the unit is a crash loop whose only line names no key.
    Called at startup (assert_configured_workspace), never at import:
    installation/check imports this module and words its own remedy per errno."""
    try:
        with open(TOKEN_FILE) as f:
            f.read(1)
    except OSError as e:
        sys.exit(f"WATCH-CONFIG {CONFIG_FILE}: token.path {TOKEN_FILE} cannot be read "
                 f"({e.strerror or e})")


def assert_configured_workspace() -> None:
    """Refuse to poll a workspace the config was not written for.

    The config names a workspace; the token file decides which workspace is
    actually reached. Nothing keeps those in step, and pointing this watcher at
    a second workspace means editing both - so the mismatch is a real mistake,
    not a hypothetical. Left unchecked it is also a SILENT one: the watcher
    happily polls the token's workspace while every ID in the config (bot user,
    known-user labels, the charter's authorization table keyed to them) belongs
    to the other one, which surfaces as strangers posting under familiar names.
    One auth.test call at startup, once per process, after the token file is
    known to be readable.
    """
    assert_token_readable()
    team = api("auth.test").get("team_id")
    if team != TEAM_ID:
        sys.exit(
            f"WATCH-CONFIG workspace mismatch: token belongs to team {team}, but "
            f"{CONFIG_FILE} declares {TEAM_ID} ({WORKSPACE_DOMAIN}). Refusing to poll."
        )


def main() -> None:
    once = "--once" in sys.argv
    # --once = the smoke test, which runs beside the live watcher: it skips the owner
    # guard and the lock both, and SKILL.md (Ownership) says so.
    if not once:
        _lock = acquire_singleton_lock()  # noqa: F841 - held for process lifetime
    # ⚠️ SIGTERM's default action ends the process without running a single
    # `finally`: the cursors a poll or sweep in flight had advanced - their lines
    # already printed - would not be saved, and the restarted watcher would print
    # them again. `Terminated` passes every `except Exception` below and runs the
    # saves on its way out; `run()` then ends the process by the signal.
    signal.signal(signal.SIGTERM, _on_sigterm)
    assert_configured_workspace()
    # No seed: discovery owns the channel set outright - the bot is a member of
    # many channels and none is privileged. Until the first discovery returns,
    # the set is empty and nothing is polled; cursors on disk make that a delay,
    # not a loss (see the module docstring).
    channels: dict[str, str] = {}
    dms: dict[str, str] = {}       # {dm_id: partner_uid}; empty until im scopes exist
    dm_warn: dict = {}             # one-shot missing_scope warn latch for discover_dms
    chan_warn: dict = {}           # one-shot missing_scope warn latch for private channels
    states: dict[str, dict] = {}
    # Conversations Slack says are gone/unreadable (GONE_CONVERSATION_ERRORS).
    # Process-scoped on purpose: a restart re-probes every one of them, so a
    # retirement can never outlive the condition that caused it by more than one
    # watcher lifetime, and nothing has to be un-stuck by hand.
    retired: set[str] = set()
    sweeps: dict[str, dict] = {}   # sweeps in progress, {conversation id: position}
    poll_count = 0
    while True:
        if poll_count % REDISCOVER_EVERY == 0:
            try:
                discovered = discover_channels(chan_warn)
                if discovered:  # keep last known set on an empty/failed discovery
                    channels = discovered
            except Exception as e:  # transient API failure must not lose the channel set
                print(f"WATCH-ERROR discovery {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            try:
                # {} on missing_scope (logged once) or a transient failure keeps the
                # last known DM set; re-probed every cycle so DMs light up on reinstall.
                dms = discover_dms(dm_warn)
            except Exception as e:
                print(f"WATCH-ERROR dm-discovery {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            # A retirement survives rediscovery as long as the conversation is
            # STILL in the watched set - otherwise the ~60s cycle would re-add it
            # and the flood would resume at one line per rediscovery. Dropping
            # out of discovery is the one event that clears it: the conversation
            # left the watched set entirely, so a later reappearance is a new
            # conversation as far as this process knows, and gets one fresh probe
            # (and at most one fresh WATCH-INFO). Pruning against the EFFECTIVE
            # sets, not against this cycle's raw results, is what keeps a
            # transient discovery failure - which deliberately keeps the last
            # known set - from un-retiring everything and re-flooding. A sweep
            # in progress is forgotten the same way.
            retired.intersection_update(channels.keys() | dms.keys())
            for gone in sweeps.keys() - (channels.keys() | dms.keys()):
                del sweeps[gone]
        # ONE budget per poll for every sweep's calls, shared by all conversations,
        # so sweeps in progress together cannot stack (SKILL.md, the sweep's cost).
        budget = None if once else {"left": SWEEP_BUDGET}
        watched = [(c, n, False) for c, n in channels.items()] + [(d, u, True) for d, u in dms.items()]
        # ⚠️ The shared budget is first-come, so the order rotates every poll: in a fixed
        # order a saturated budget would never reach the conversations at the end.
        turn = poll_count % len(watched) if watched else 0
        watched = watched[turn:] + watched[:turn]
        for cid, name, is_dm in watched:
            if cid in retired:
                continue
            try:
                state = states.get(cid)
                if state is None:
                    state = states[cid] = load_state(cid)
                # ⚠️ Saved even when the poll raises: the cursors move message by
                # message, so a failed poll's state records what it delivered, and
                # a restart before the next good poll does not deliver it again.
                # Not while the state is still empty (a first sight that failed),
                # so a conversation never polled successfully leaves no file.
                try:
                    edge = poll_channel(cid, name, state, is_dm=is_dm)
                finally:
                    if state:
                        save_state(cid, state)
            except Exception as e:  # one conversation's failure must not kill the whole watch
                reason = gone_conversation_reason(e)
                if reason:
                    retired.add(cid)
                    print(f"WATCH-INFO retired {_where(cid, name, is_dm, with_id=True)}: Slack says "
                          f"{reason} - not polled again by this process unless it leaves discovery "
                          f"and returns", file=sys.stderr, flush=True)
                else:
                    print(f"WATCH-ERROR {_where(cid, name, is_dm)} {type(e).__name__}: {e}",
                          file=sys.stderr, flush=True)
                continue  # a poll that failed reached no edge: no sweep this cycle
            if cid in sweeps or once or sweep_due(cid, poll_count):
                run_sweep(cid, name, state, edge, sweeps, budget, is_dm=is_dm)
        poll_count += 1
        if once:
            return
        time.sleep(POLL_SECS)


class Terminated(BaseException):
    """Raised by the SIGTERM handler. A BaseException, so no `except Exception`
    swallows it and every `finally` on its way out runs."""


def _on_sigterm(*_) -> None:
    raise Terminated()


def run() -> None:
    """The entry point. ⚠️ A SIGTERM ends the process BY the signal, after the
    saves, never with exit 0: a supervisor that restarts on a signal death treats
    exit 0 as a deliberate stop - it is how the WATCH-GUARD refusals stop the
    service - so a terminated watcher that exited 0 would stay down after an
    ad-hoc `kill`. The WATCH-GUARD `sys.exit(0)` is a SystemExit, not caught here,
    and still exits 0."""
    try:
        main()
    except Terminated:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    run()
