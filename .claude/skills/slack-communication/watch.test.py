#!/usr/bin/env python3
"""Regression guard for the Slack watcher.

Pins `initial_baseline()` - the pure decision the watcher makes on FIRST sight of
a channel - plus channel/DM discovery (public + PRIVATE + im), the emit format,
threads off the page and the sweep, retirement, the read retry and the config
surface. The first-sight case it opens with: a baseline taken blindly at "now"
swallows every message posted between the `/invite` and the first ~60s
discovery poll - the bot joins at ts 1784577731, a human posts at 1784577739,
the watcher baselines at ~1784577770 and never emits it.

Pure and offline - no network, no token, no live posting. The fixtures keep the
SHAPE of recorded conversations.history payloads (keys, nesting, which keys are
absent) with synthetic ids, names and text.

The config is forced to config.example.json BEFORE watch.py is imported (below),
so this runs in a tree that holds no config.json - the fleet repository's own -
and never against the caller's live config.
Run: python3 watch.test.py  (from any directory; exits nonzero on any failure).
"""
import contextlib
import http.client
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import urllib.request

# The guard runs against the EXAMPLE config, never the caller's and never an
# install's. Forced, not defaulted: an ambient SLACK_WATCH_CONFIG (every agent that
# arms a watcher exports one) would silently re-point BOT_USER and KNOWN_USERS at a
# live workspace, and the whole in-process half of this file would then measure
# that workspace instead. Without a value watch.py refuses to start, because the
# variable is its only configuration channel (section 11c-ii). The subprocess
# config cases below pass their own fixture explicitly, so they are unaffected.
os.environ["SLACK_WATCH_CONFIG"] = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "config.example.json")

# watch.py's signatures use PEP-604 unions (`str | None`) and it carries no
# `from __future__ import annotations`, so they are evaluated at def time: on
# python3 < 3.10 the import below dies with
# `TypeError: unsupported operand type(s) for |` at whichever def comes first.
# Said here because this test runs on whatever python3 the machine running it
# has - CI pins one, a contributor's or a host's machine need not - and a
# version failure that surfaces as a TypeError inside an import reads as a
# broken watcher rather than a runner that is too old. Refuse by name instead.
if sys.version_info < (3, 10):
    sys.exit(
        f"watch.test.py: needs python3 >= 3.10 (watch.py uses PEP-604 unions in "
        f"its signatures); this interpreter is {sys.version.split()[0]}"
    )

_SCRIPT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "watch.py")
_spec = importlib.util.spec_from_file_location("slack_watch", _SCRIPT)
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

# Sections below replace w.emit with capture stubs. Section 14 asserts the REAL
# emit line, so keep a handle on it here, before the first stub is installed.
_REAL_EMIT = w.emit

# Same reason, for `api`: sections above replace `w.api` wholesale with fixture
# stubs, so by the time section 16 runs, `w.api` is somebody else's fake and a
# section that calls it measures the fake. Measured: without this handle every
# check in 16 reported against `_bot_poll_api`, the regime control catching it
# at 0 requests issued. Keep the real function here, before the first stub.
_REAL_API = w.api

BOT = w.BOT_USER
# The synthetic people of these fixtures, labelled the way an install's
# known_users labels its own: the emit-line checks read these names back.
w.KNOWN_USERS = {**w.KNOWN_USERS, "U0ADA": "Ada", "U0GRACE": "Grace"}
JOIN_TS = "1784577731.070209"
HUMAN_MSG_TS = "1784577739.450929"

# A recorded first-sight payload's shape: the bot's own channel_join, then a human's message.
REAL_INVITE_WINDOW = [
    {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join",
     "text": f"<@{BOT}> has joined the channel"},
    {"ts": HUMAN_MSG_TS, "user": "U0ADA", "subtype": None,
     "text": "hey, are you around?"},
]

_failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


# 1. JOIN BRANCH (real data): the just-invited bot replays messages after its join.
baseline, emitted = w.initial_baseline(list(REAL_INVITE_WINDOW), now=1784577770.0)
check("join-in-window replays the human message",
      [(m["user"], m["text"]) for m in emitted] == [("U0ADA", "hey, are you around?")],
      f"emitted={[m['text'] for m in emitted]}")
check("join-in-window baselines cursor to the newest replayed msg",
      baseline == HUMAN_MSG_TS, f"baseline={baseline}")

# 1b. TEETH - a baseline-to-now that emits nothing swallows it.
check("join-branch emits >=1 (a baseline-to-now emits 0: the bug this pins)",
      len(emitted) >= 1, f"emitted {len(emitted)}")

# 2. NO-JOIN BRANCH: no recent join (returning session / old membership) → baseline
#    to now, replay nothing. An empty window is what the `oldest` API filter yields
#    when the join is older than RECENT_JOIN_WINDOW_SECS.
baseline2, emitted2 = w.initial_baseline([], now=1784577770.0)
check("no-join baselines to now", baseline2 == "1784577770.000000", f"baseline={baseline2}")
check("no-join replays nothing", emitted2 == [], f"emitted={emitted2}")

# 2b. No-join even when history exists but contains no BOT channel_join (e.g. only
#     someone else's join + their chatter): must NOT replay, must baseline to now.
other = [
    {"ts": "1784577700.0", "user": "U0ADA", "subtype": "channel_join",
     "text": "ada has joined"},
    {"ts": "1784577705.0", "user": "U0ADA", "subtype": None, "text": "old chatter"},
]
b_other, e_other = w.initial_baseline(other, now=1784577770.0)
check("someone-else's-join is not the bot's join → baseline to now",
      b_other == "1784577770.000000" and e_other == [], f"baseline={b_other} emitted={e_other}")

# 3. TEETH - a human message posted BEFORE the join must not be replayed (only ts>join).
pre_and_post = [
    {"ts": "1784577720.0", "user": "U0ADA", "subtype": None, "text": "before join"},
    {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"},
    {"ts": HUMAN_MSG_TS, "user": "U0ADA", "subtype": None, "text": "after join"},
]
_, e_pre = w.initial_baseline(pre_and_post, now=1784577770.0)
check("pre-join message is NOT replayed; post-join IS",
      [m["text"] for m in e_pre] == ["after join"], f"emitted={[m['text'] for m in e_pre]}")

# 4. The bot's own post-join messages and user-less app posts are filtered
#    (is_deliverable; the full delivery rule is section 14).
noisy = [
    {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"},
    {"ts": "1784577740.0", "user": BOT, "subtype": None, "text": "the bot's own reply"},
    {"ts": "1784577741.0", "bot_id": "B123", "subtype": None, "text": "some app"},
    {"ts": "1784577742.0", "user": "U0ADA", "subtype": None, "text": "real human"},
]
b_noisy, e_noisy = w.initial_baseline(noisy, now=1784577770.0)
check("bot/app messages filtered, only the human replayed",
      [m["text"] for m in e_noisy] == ["real human"], f"emitted={[m['text'] for m in e_noisy]}")
check("cursor advances past the newest message even when bot msgs are newest",
      b_noisy == "1784577742.0", f"baseline={b_noisy}")

# 5. Rejoin: a later channel_join wins, so only messages after the LATEST join replay.
rejoin = [
    {"ts": "1784577731.0", "user": BOT, "subtype": "channel_join", "text": "join1"},
    {"ts": "1784577735.0", "user": "U0ADA", "subtype": None, "text": "between joins"},
    {"ts": "1784577740.0", "user": BOT, "subtype": "channel_join", "text": "join2"},
    {"ts": "1784577745.0", "user": "U0ADA", "subtype": None, "text": "after latest join"},
]
_, e_re = w.initial_baseline(rejoin, now=1784577770.0)
check("latest channel_join wins (rejoin replays only the newest slice)",
      [m["text"] for m in e_re] == ["after latest join"], f"emitted={[m['text'] for m in e_re]}")

# 6. Join found but no human message after it → baseline to the join ts (not now),
#    so the next normal poll picks up from immediately after the join.
just_join = [{"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"}]
b_j, e_j = w.initial_baseline(just_join, now=1784577770.0)
check("join with no later human msg baselines to the join ts",
      b_j == JOIN_TS and e_j == [], f"baseline={b_j} emitted={e_j}")

# === DMs: discovery merge, missing-scope grace, first-sight window, line format ===
# All pure/offline - stubbed api() and captured stdout/stderr, no network.

_DM_CHANNELS = {"channels": [
    {"id": "D111", "user": "U0GRACE", "is_im": True},   # Grace
    {"id": "D222", "user": "U0ADA", "is_im": True},   # Ada
]}

# 10. DM discovery: a types=im users.conversations result → {dm_id: partner_uid}.
def _dm_api(method, **params):
    check("DM discovery queries users.conversations with types=im",
          method == "users.conversations" and params.get("types") == "im",
          f"method={method} params={params}")
    return _DM_CHANNELS
w.api = _dm_api
_warn = {}
_dms = w.discover_dms(_warn)
check("DM discovery maps id → partner uid",
      _dms == {"D111": "U0GRACE", "D222": "U0ADA"}, f"dms={_dms}")

# 11. missing_scope grace: probe fails → log ONCE, return {} (channels-only), and
#     a later successful re-probe recovers DMs with no restart (re-arms the latch).
_scope = {"granted": False}
def _scope_api(method, **params):
    if not _scope["granted"]:
        raise RuntimeError("users.conversations: missing_scope")
    return _DM_CHANNELS
w.api = _scope_api
_warn2 = {}
_errbuf = io.StringIO()
with contextlib.redirect_stderr(_errbuf):
    _r1 = w.discover_dms(_warn2)   # first miss → logs one line
    _r2 = w.discover_dms(_warn2)   # second miss → silent (latched, no per-poll spam)
_loglines = [ln for ln in _errbuf.getvalue().splitlines() if ln.strip()]
check("missing_scope returns empty DM set (fall back to channels-only)",
      _r1 == {} and _r2 == {}, f"r1={_r1} r2={_r2}")
check("missing_scope logs exactly ONE line across repeated probes (no spam)",
      len(_loglines) == 1, f"lines={_loglines}")
check("missing_scope line names the im scopes",
      bool(_loglines) and "im:read" in _loglines[0], f"line={_loglines[0] if _loglines else None}")
_scope["granted"] = True  # an admin reinstalls with im scopes
_r3 = w.discover_dms(_warn2)
check("re-probe after reinstall recovers DMs automatically (no restart)",
      _r3 == {"D111": "U0GRACE", "D222": "U0ADA"}, f"r3={_r3}")
check("successful re-probe re-arms the one-shot warn latch",
      _warn2.get("logged") is False, f"warn={_warn2}")

# 12. First-seen DM baseline window (now - DM_BASELINE_WINDOW_SECS): a message
#     inside the window is replayed, pre-window history is NOT (bounded, no
#     months-old replay), and the bot's own DM messages are filtered.
WIN = "1784577680.000000"
dm_hist = [
    {"ts": "1784577600.0", "user": "U0GRACE", "subtype": None, "text": "pre-window (older)"},
    {"ts": "1784577700.0", "user": "U0GRACE", "subtype": None, "text": "opening msg (in window)"},
]
b_dm, e_dm = w.dm_initial_baseline(dm_hist, WIN)
check("DM first-sight replays only the in-window message (older history dropped)",
      [m["text"] for m in e_dm] == ["opening msg (in window)"], f"emitted={[m['text'] for m in e_dm]}")
check("DM first-sight baselines cursor to the newest replayed msg",
      b_dm == "1784577700.0", f"baseline={b_dm}")
b_empty, e_empty = w.dm_initial_baseline(
    [{"ts": "1784577600.0", "user": "U0GRACE", "subtype": None, "text": "old"}], WIN)
check("DM first-sight with only pre-window history replays nothing, baselines to window edge",
      e_empty == [] and b_empty == WIN, f"baseline={b_empty} emitted={e_empty}")
_, e_botdm = w.dm_initial_baseline(
    [{"ts": "1784577700.0", "user": BOT, "subtype": None, "text": "the bot's own dm reply"}], WIN)
check("DM first-sight filters the bot's own messages (is_deliverable)", e_botdm == [], f"emitted={e_botdm}")

# 13. DM line format: `SLACK DM ... Name (UID): text` - no #channel, thread marker kept.
_outbuf = io.StringIO()
with contextlib.redirect_stdout(_outbuf):
    w.emit({"ts": "1784577700.0", "user": "U0GRACE", "text": "hey there"},
           "U0GRACE", is_dm=True)
    w.emit({"ts": "1784577701.0", "user": "U0GRACE", "text": "in a thread"},
           "U0GRACE", parent_ts="1784577700.0", is_dm=True)
_dmlines = _outbuf.getvalue().splitlines()
check("DM top-level line format",
      _dmlines[0] == "SLACK DM message [ts 1784577700.0] Grace (U0GRACE): hey there",
      f"line={_dmlines[0]!r}")
check("DM thread-reply line keeps the thread marker",
      _dmlines[1] == "SLACK DM reply in thread 1784577700.0 [ts 1784577701.0] Grace (U0GRACE): in a thread",
      f"line={_dmlines[1]!r}")
_chbuf = io.StringIO()
with contextlib.redirect_stdout(_chbuf):
    w.emit({"ts": "1.0", "user": "U0GRACE", "text": "x"}, "random")  # is_dm defaults False
check("channel emit still renders #name, never 'DM' (no regression)",
      _chbuf.getvalue().strip() == "SLACK #random message [ts 1.0] Grace (U0GRACE): x",
      f"line={_chbuf.getvalue().strip()!r}")

# === PRIVATE CHANNELS: discovery merge, coexistence, join-replay, emit format ===
# The bot has groups:read (verified 2026-07-21), so ONE users.conversations call
# with types=public_channel,private_channel returns both. A private channel is
# polled and emitted exactly like a public one (is_dm=False) - it still has a name.
# All pure/offline - stubbed api() + captured output, no network, no live posting.

_MIXED_CHANNELS = {"channels": [
    {"id": "C_PUB", "name": "random", "is_channel": True, "is_private": False},
    {"id": "G_PRIV", "name": "private-team", "is_channel": True, "is_private": True},
]}

# P1. Combined discovery: types=public_channel,private_channel returns BOTH, and a
#     private channel is merged into the watched set exactly like a public one.
_saved_emit = w.emit  # restore after the poll_channel integration below
def _mixed_api(method, **params):
    check("channel discovery requests public AND private types",
          method == "users.conversations"
          and params.get("types") == "public_channel,private_channel",
          f"method={method} types={params.get('types')}")
    return _MIXED_CHANNELS
w.api = _mixed_api
_chwarn = {}
_chans = w.discover_channels(_chwarn)
check("private channel is discovered and watched alongside the public one",
      _chans == {"C_PUB": "random", "G_PRIV": "private-team"}, f"channels={_chans}")
check("full (private-included) probe re-arms the one-shot warn latch",
      _chwarn.get("logged") is False, f"warn={_chwarn}")

# P2. Coexistence: public + private (discover_channels) and im (discover_dms) are
#     disjoint sets keyed by distinct ids - nothing collides.
def _im_api(method, **params):
    return _DM_CHANNELS  # types=im path (reused from the DM section)
w.api = _im_api
_ims = w.discover_dms({})
_all_ids = set(_chans) | set(_ims)
check("public + private + im all coexist as disjoint id sets",
      _all_ids == {"C_PUB", "G_PRIV", "D111", "D222"} and len(_all_ids) == 4,
      f"chans={set(_chans)} ims={set(_ims)}")

# P3. Combined-types missing_scope grace: if the private scope is ever lost, the
#     combined call fails → degrade to public-only, log ONCE (no per-cycle spam),
#     never lose the public channels, and re-arm only on a full-scope recovery.
_priv_scope = {"granted": False}
_PUBLIC_ONLY = {"channels": [{"id": "C_PUB", "name": "random", "is_private": False}]}
def _priv_scope_api(method, **params):
    if "private_channel" in params.get("types", "") and not _priv_scope["granted"]:
        raise RuntimeError("users.conversations: missing_scope")
    return _MIXED_CHANNELS if _priv_scope["granted"] else _PUBLIC_ONLY
w.api = _priv_scope_api
_pwarn = {}
_perr = io.StringIO()
with contextlib.redirect_stderr(_perr):
    _pc1 = w.discover_channels(_pwarn)   # combined fails → fall back to public-only, log once
    _pc2 = w.discover_channels(_pwarn)   # still missing → silent (latched)
_plines = [ln for ln in _perr.getvalue().splitlines() if ln.strip()]
check("missing private scope degrades to public-only (public channels NOT lost)",
      _pc1 == {"C_PUB": "random"} and _pc2 == {"C_PUB": "random"}, f"pc1={_pc1} pc2={_pc2}")
check("missing private scope logs exactly ONE line across repeated probes (no spam)",
      len(_plines) == 1, f"lines={_plines}")
check("missing private scope line names groups:read",
      bool(_plines) and "groups:read" in _plines[0], f"line={_plines[0] if _plines else None}")
_priv_scope["granted"] = True  # scope restored
_pc3 = w.discover_channels(_pwarn)
check("re-probe after scope restored recovers private channels (no restart)",
      _pc3 == {"C_PUB": "random", "G_PRIV": "private-team"}, f"pc3={_pc3}")
check("recovered full probe re-arms the one-shot warn latch",
      _pwarn.get("logged") is False, f"warn={_pwarn}")

# P4. Emit format: a private channel renders `SLACK #<name> ...`, identical to a
#     public channel - never 'DM', no special private prefix (is_dm=False).
_pbuf = io.StringIO()
with contextlib.redirect_stdout(_pbuf):
    _saved_emit({"ts": "1784577900.0", "user": "U0GRACE", "text": "hi in private"},
                "private-team")  # is_dm defaults False
check("private channel emit renders #name (same format as public, never 'DM')",
      _pbuf.getvalue().strip()
      == "SLACK #private-team message [ts 1784577900.0] Grace (U0GRACE): hi in private",
      f"line={_pbuf.getvalue().strip()!r}")

# P5. First-sight invite-race join-replay flows through UNCHANGED for a private
#     channel: poll_channel(is_dm=False) on a freshly-invited private channel
#     replays the human message posted after the bot's channel_join marker.
_priv_emitted = []
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _priv_emitted.append((channel_name, msg["text"], is_dm))
def _priv_join_hist(method, **params):
    return {"messages": [
        {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"},
        {"ts": HUMAN_MSG_TS, "user": "U0ADA", "subtype": None, "text": "hello (in private)"},
    ]}
w.api = _priv_join_hist
st_priv = {}
w.poll_channel("G_PRIV", "private-team", st_priv)  # is_dm defaults False (a channel)
check("private-channel first-sight replays the post-join message (as a channel, not DM)",
      _priv_emitted == [("private-team", "hello (in private)", False)], f"emitted={_priv_emitted}")
check("private-channel first-sight writes {channel_ts, baseline_ts, threads} state",
      st_priv.get("channel_ts") == HUMAN_MSG_TS and st_priv.get("baseline_ts") == JOIN_TS
      and st_priv.get("threads") == {}, f"state={st_priv}")
w.emit = _saved_emit  # restore the real emit for any following real-emit checks

# --- Integration: poll_channel first-sight driven through a stubbed api() ---
# These pin the parts initial_baseline can't reach: the clean-retry-on-failure
# state invariant, that a non-empty state skips the first-sight window fetch, and
# that pagination recovers the join when a busy window pushes it off page 1.
_emitted = []
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _emitted.append((channel_name, msg["text"]))

# 7. First-sight API failure: exception propagates and state stays EMPTY (no
#    half-mutation), so the next poll cleanly retries first-sight.
def _boom(method, **params):
    raise RuntimeError("transient API failure")
w.api = _boom
st = {}
try:
    w.poll_channel("C1", "general", st)
    check("first-sight API failure propagates (caught by main loop)", False, "no exception")
except RuntimeError:
    check("first-sight API failure propagates (caught by main loop)", True)
check("failed first-sight leaves state empty for a clean retry", st == {}, f"state={st}")

# ...and the retry then replays the swallowed message and writes full state.
_emitted.clear()
def _hist_join(method, **params):
    return {"messages": [
        {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"},
        {"ts": HUMAN_MSG_TS, "user": "U0ADA", "subtype": None, "text": "hey, are you around?"},
    ]}
w.api = _hist_join
w.poll_channel("C1", "general", st)
check("retry after failure replays the swallowed message",
      _emitted == [("general", "hey, are you around?")], f"emitted={_emitted}")
check("retry writes {channel_ts, baseline_ts, threads} state",
      st.get("channel_ts") == HUMAN_MSG_TS and st.get("baseline_ts") == JOIN_TS
      and st.get("threads") == {}, f"state={st}")

# 8. Non-empty (existing) state must SKIP first-sight - no `oldest` window fetch,
#    normal poll path only. Guards against re-triggering replay on upgrade.
_calls = []
def _record(method, **params):
    _calls.append(params)
    return {"messages": [
        {"ts": "1784577800.0", "user": "U0ADA", "subtype": None, "text": "new normal msg"},
    ]}
w.api = _record
_emitted.clear()
st2 = {"channel_ts": "1784577750.0", "threads": {}}
w.poll_channel("C1", "general", st2)
check("non-empty state skips first-sight (never issues an 'oldest' window fetch)",
      all("oldest" not in c for c in _calls), f"calls={_calls}")
check("normal path still emits messages newer than the cursor",
      _emitted == [("general", "new normal msg")], f"emitted={_emitted}")

# 9. Busy invite window: >1 page of post-join traffic pushes the join marker onto
#    page 2. Pagination must recover it (without it, page 1 has no join → baseline
#    to now → the target after the join is never fetched → swallowed again).
_pages = [
    {"messages": [{"ts": f"1784577900.{i:03d}", "user": "U0ADA",
                   "subtype": None, "text": f"busy {i}"} for i in range(200)],
     "response_metadata": {"next_cursor": "PAGE2"}},
    {"messages": [
        {"ts": JOIN_TS, "user": BOT, "subtype": "channel_join", "text": "joined"},
        {"ts": HUMAN_MSG_TS, "user": "U0ADA", "subtype": None, "text": "the target msg"},
    ]},
]
def _paged(method, **params):
    return _pages[1] if params.get("cursor") == "PAGE2" else _pages[0]
w.api = _paged
_emitted.clear()
st3 = {}
w.poll_channel("C1", "general", st3)
check("busy window: pagination recovers the join on page 2 → target replayed",
      ("general", "the target msg") in _emitted, f"emitted count={len(_emitted)}")

# 10i. DM first-sight through poll_channel(is_dm=True): the first-sight fetch uses
#      the `oldest` window, only the in-window message emits (recorded with the DM's
#      partner uid as channel_name), and {channel_ts, baseline_ts, threads} state
#      is written - the DM's baseline_ts is the window floor, not the newest
#      message emitted, so a reply posted inside the window still surfaces.
_now = w.time.time()
def _dm_first_sight(method, **params):
    check("DM first-sight fetch uses the 'oldest' window filter",
          method == "conversations.history" and "oldest" in params, f"method={method} params={params}")
    return {"messages": [
        {"ts": f"{_now - 1000:.6f}", "user": "U0GRACE", "subtype": None, "text": "old dm"},
        {"ts": f"{_now - 10:.6f}", "user": "U0GRACE", "subtype": None, "text": "fresh dm"},
    ]}
w.api = _dm_first_sight
_emitted.clear()
st_dm = {}
w.poll_channel("D111", "U0GRACE", st_dm, is_dm=True)
check("DM poll first-sight emits only the in-window message (tagged with partner uid)",
      _emitted == [("U0GRACE", "fresh dm")], f"emitted={_emitted}")
check("DM poll first-sight writes {channel_ts, baseline_ts, threads} state",
      st_dm.get("channel_ts") == f"{_now - 10:.6f}"
      and abs(float(st_dm.get("baseline_ts", 0)) - (_now - w.DM_BASELINE_WINDOW_SECS)) < 1
      and st_dm.get("threads") == {}, f"state={st_dm}")

# 10j. DM first-sight clean-retry: an API failure propagates and leaves state EMPTY
#      (no half-mutation), so the next poll cleanly retries - same invariant as channels.
w.api = _boom
st_dm2 = {}
try:
    w.poll_channel("D111", "U0GRACE", st_dm2, is_dm=True)
    check("DM first-sight API failure propagates (caught by main loop)", False, "no exception")
except RuntimeError:
    check("DM first-sight API failure propagates (caught by main loop)", True)
check("failed DM first-sight leaves state empty for a clean retry", st_dm2 == {}, f"state={st_dm2}")

# === 10t. THREAD REPLIES OBEY THE FIRST-SIGHT BASELINE ==========================
# The invariant: NO message - top-level or thread reply - with a ts earlier than
# the channel's first-sight baseline is ever emitted; a reply posted AFTER the
# baseline is emitted even when its parent is older than the baseline (the
# invite-race case the baseline exists for).
#
# The bug this pins: a first sight that baselines channel_ts to the bot's own join
# ts but seeds threads={}, while the normal poll defaults a cursorless thread to its
# PARENT ts, makes the next poll replay every reply of every thread among the last
# 50 top-level messages as if live (measured 2026-09-02: ~100 replies going back
# three weeks, 45 minutes after the invite).
#
# What makes these checks have teeth: the stubbed conversations.replies returns
# BOTH replies regardless of the `oldest` it is handed, so the suppression can
# only come from the watcher's own cursor arithmetic and never from the stub
# pretending Slack filtered. The `oldest` a real Slack call would receive is
# asserted separately, so the two halves cannot cover for each other.
_thread_emitted = []
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _thread_emitted.append(
    (msg["text"], parent_ts))

_J = "3000.000000"          # the bot's own channel_join - the first-sight baseline
_OLD_PARENT = "1000.000000"  # a thread started three weeks before the invite
_REPLY_BEFORE = "1500.000000"
_REPLY_AFTER = "3500.000000"
_replies_oldest = []


def _thread_api(method, **params):
    if method == "conversations.history" and "oldest" in params:
        # First-sight window: the bot's join, nothing else in the window.
        return {"messages": [{"ts": _J, "user": BOT, "subtype": "channel_join",
                              "text": "joined"}]}
    if method == "conversations.history":
        # Normal poll: the last 50 top-level messages reach back PAST the window.
        return {"messages": [{"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "three-week-old thread parent",
                              "reply_count": 2, "latest_reply": _REPLY_AFTER}]}
    if method == "conversations.replies":
        _replies_oldest.append(params.get("oldest"))
        return {"messages": [
            {"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": _REPLY_BEFORE, "user": "U0ADA", "subtype": None, "text": "reply before J"},
            {"ts": _REPLY_AFTER, "user": "U0ADA", "subtype": None, "text": "reply after J"},
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _thread_api
st_thr = {}
w.poll_channel("C_THR", "builds", st_thr)          # first sight: baseline only
check("first sight persists the baseline it applied as baseline_ts",
      st_thr.get("baseline_ts") == _J, f"state={st_thr}")
_thread_emitted.clear()
w.poll_channel("C_THR", "builds", st_thr)          # the next normal poll
check("old thread: replies BEFORE the first-sight baseline are never emitted",
      ("reply before J", _OLD_PARENT) not in _thread_emitted, f"emitted={_thread_emitted}")
check("old thread: the reply AFTER the baseline IS emitted (the invite-race case)",
      _thread_emitted == [("reply after J", _OLD_PARENT)], f"emitted={_thread_emitted}")
check("a cursorless thread is fetched from the baseline, not from its parent ts",
      _replies_oldest == [_J], f"oldest={_replies_oldest}")

# REGIME CONTROL - this test must exercise a thread whose parent is OLDER than the
# baseline, which is the only case the bug had. A fixture that drifted to a
# post-baseline parent would still go green while measuring nothing: max(parent,
# baseline) equals the parent there, i.e. exactly the unfixed behaviour.
check("REGIME CONTROL: the fixture's parent really is older than the baseline",
      float(_OLD_PARENT) < float(_J) < float(_REPLY_AFTER),
      f"parent={_OLD_PARENT} baseline={_J}")

# A thread whose parent is NEWER than the baseline is untouched: every reply of it
# is emitted, because max(parent, baseline) is the parent ts there.
_NEW_PARENT = "3200.000000"
_replies_oldest.clear()
_thread_emitted.clear()


def _new_thread_api(method, **params):
    if method == "conversations.history":
        return {"messages": [{"ts": _NEW_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "thread started after the invite",
                              "reply_count": 1, "latest_reply": "3600.000000"}]}
    if method == "conversations.replies":
        _replies_oldest.append(params.get("oldest"))
        return {"messages": [
            {"ts": _NEW_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": "3600.000000", "user": "U0ADA", "subtype": None, "text": "reply in a new thread"},
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _new_thread_api
st_new = {"channel_ts": _J, "baseline_ts": _J, "threads": {}}
w.poll_channel("C_THR", "builds", st_new)
check("a thread STARTED after the baseline still emits its parent and all replies",
      _thread_emitted == [("thread started after the invite", None),
                          ("reply in a new thread", _NEW_PARENT)]
      and _replies_oldest == [_NEW_PARENT], f"emitted={_thread_emitted} oldest={_replies_oldest}")

# 10u. PRE-EXISTING state files carry no baseline_ts and are never migrated: the
#      floor falls back to the channel cursor already on disk. Live cursors keep
#      working - a reply posted from now on has a ts later than any past cursor,
#      so nothing arriving after the upgrade can be suppressed - while history
#      older than that cursor stays unemitted, which is strictly less replay than
#      the unfixed code produced from the same file.
_replies_oldest.clear()
_thread_emitted.clear()
_LEGACY_CURSOR = "3000.000000"
_LEGACY_LATEST = "3900.000000"


def _legacy_api(method, **params):
    if method == "conversations.history":
        return {"messages": [{"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "old parent", "reply_count": 2,
                              "latest_reply": _LEGACY_LATEST}]}
    if method == "conversations.replies":
        _replies_oldest.append(params.get("oldest"))
        return {"messages": [
            {"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": _REPLY_BEFORE, "user": "U0ADA", "subtype": None, "text": "legacy old reply"},
            {"ts": _LEGACY_LATEST, "user": "U0ADA", "subtype": None, "text": "legacy new reply"},
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _legacy_api
st_legacy = {"channel_ts": _LEGACY_CURSOR, "threads": {}}   # no baseline_ts: pre-existing file
w.poll_channel("C_THR", "builds", st_legacy)
check("pre-existing state (no baseline_ts): history older than its cursor is not replayed",
      ("legacy old reply", _OLD_PARENT) not in _thread_emitted, f"emitted={_thread_emitted}")
check("pre-existing state (no baseline_ts): a reply newer than its cursor still emits",
      _thread_emitted == [("legacy new reply", _OLD_PARENT)], f"emitted={_thread_emitted}")
check("pre-existing state is not migrated - no baseline_ts is written into it",
      "baseline_ts" not in st_legacy, f"state={st_legacy}")

w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _emitted.append(
    (channel_name, msg["text"]))   # restore the section's emit stub

# 10v. THE BASELINE IS NOT THE CURSOR - the check that makes the mechanism
#      undeletable. Every fixture above has channel_ts == baseline_ts, so all of
#      them stay green if `baseline_ts` is dropped and `channel_ts` used as the
#      floor. This one separates them: first sight emits a top-level message
#      posted AFTER the join, which advances channel_ts past a thread reply that
#      still has to surface.
#
#      MUTATION CONTROLS - both were run and both go RED on this check alone:
#        A1  floor = state["channel_ts"]                 (drop the new field's use)
#        A2  state["baseline_ts"] = baseline             (store the cursor, not the floor)
#      Delete this check and the whole argument for a second stored ts becomes
#      unfalsifiable, which is how a load-bearing field gets "simplified" away.
_J2 = "3000.000000"        # the bot's own join = the baseline
_MID_REPLY = "3200.000000"  # a reply in an OLD thread, after the join
_TOP_AFTER = "3400.000000"  # a top-level message after the join: first sight emits it
_thread_emitted.clear()
_replies_oldest.clear()
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _thread_emitted.append(
    (msg["text"], parent_ts))


def _race_api(method, **params):
    if method == "conversations.history" and "oldest" in params:
        return {"messages": [
            {"ts": _J2, "user": BOT, "subtype": "channel_join", "text": "joined"},
            {"ts": _TOP_AFTER, "user": "U0ADA", "subtype": None, "text": "top-level after the join"},
        ]}
    if method == "conversations.history":
        return {"messages": [
            {"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None, "text": "old parent",
             "reply_count": 2, "latest_reply": _MID_REPLY},
            {"ts": _TOP_AFTER, "user": "U0ADA", "subtype": None, "text": "top-level after the join"},
        ]}
    if method == "conversations.replies":
        _replies_oldest.append(params.get("oldest"))
        return {"messages": [
            {"ts": _OLD_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": _REPLY_BEFORE, "user": "U0ADA", "subtype": None, "text": "reply before J"},
            {"ts": _MID_REPLY, "user": "U0ADA", "subtype": None, "text": "reply between join and cursor"},
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _race_api
st_race = {}
w.poll_channel("C_RACE", "builds", st_race)
check("the stored baseline is the JOIN, not the cursor first sight advanced to",
      st_race.get("baseline_ts") == _J2 and st_race.get("channel_ts") == _TOP_AFTER,
      f"state={st_race}")
_thread_emitted.clear()
w.poll_channel("C_RACE", "builds", st_race)
check("a reply between the join and the first-sight cursor still surfaces",
      _thread_emitted == [("reply between join and cursor", _OLD_PARENT)],
      f"emitted={_thread_emitted}")
check("REGIME CONTROL: the fixture really does put the cursor ahead of the baseline",
      float(_J2) < float(_MID_REPLY) < float(_TOP_AFTER),
      f"baseline={_J2} reply={_MID_REPLY} cursor={_TOP_AFTER}")

# 10w. A DM's floor bounds its THREAD replies too. This bot's DMs are assistant-
#      threaded (SKILL.md, "Assistant DMs"), so a human's message arrives as a
#      thread reply under a bot-authored parent that is far older than the
#      window: the reply inside the window - the one that made the DM
#      discoverable - must surface, and DM history older than it must not.
_dm_now = w.time.time()
_DM_PARENT = f"{_dm_now - 3000:.6f}"
_DM_OLD_REPLY = f"{_dm_now - 1000:.6f}"
_DM_NEW_REPLY = f"{_dm_now - 10:.6f}"
_thread_emitted.clear()


def _dm_thread_api(method, **params):
    if method == "conversations.history" and "oldest" in params:
        return {"messages": []}   # the parent predates the window
    if method == "conversations.history":
        return {"messages": [{"ts": _DM_PARENT, "user": "U0GRACE", "subtype": None,
                              "text": "assistant thread parent", "reply_count": 2,
                              "latest_reply": _DM_NEW_REPLY}]}
    if method == "conversations.replies":
        return {"messages": [
            {"ts": _DM_PARENT, "user": "U0GRACE", "subtype": None, "text": "parent"},
            {"ts": _DM_OLD_REPLY, "user": "U0GRACE", "subtype": None, "text": "dm reply before the window"},
            {"ts": _DM_NEW_REPLY, "user": "U0GRACE", "subtype": None, "text": "dm reply inside the window"},
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _dm_thread_api
st_dmt = {}
w.poll_channel("D999", "U0GRACE", st_dmt, is_dm=True)   # first sight: window floor only
_thread_emitted.clear()
w.poll_channel("D999", "U0GRACE", st_dmt, is_dm=True)
check("DM thread: the reply inside the window surfaces (assistant-threaded DMs)",
      ("dm reply inside the window", _DM_PARENT) in _thread_emitted, f"emitted={_thread_emitted}")
check("DM thread: history older than the window is not replayed",
      _thread_emitted == [("dm reply inside the window", _DM_PARENT)], f"emitted={_thread_emitted}")

# 10x. A THREAD'S CURSOR IS THE NEWEST REPLY THE POLL READ, not the parent's
#      `latest_reply`. The two calls of one poll are not one snapshot:
#      `conversations.history` reports `latest_reply` first, and the
#      `conversations.replies` call made after it can already hold newer replies
#      of the same burst. Those are emitted in this poll, so a cursor written
#      from `latest_reply` sits BEHIND them and the next poll emits them again -
#      every reply of a burst that lands within the gap between the two calls is
#      delivered twice.
#
#      Teeth: the replies stub IGNORES `oldest` and returns the whole thread
#      every time, so the second poll's silence can only come from the stored
#      cursor and never from the stub pretending Slack filtered (same rule as
#      10t). The regime control proves the fixture is the race and not an
#      ordinary poll: a fixture whose replies call returns nothing newer than
#      `latest_reply` stays green on the unfixed code while measuring nothing.
_BX_PARENT = "5000.000000"
_BX_R1 = "5001.100000"     # already seen: the stored thread cursor
_BX_R2 = "5002.200000"     # history's latest_reply at poll 1
_BX_R3 = "5002.900000"     # landed between the history call and the replies call
_bx_latest = [_BX_R2]      # what history reports as latest_reply, per poll
_bx_calls = []             # (method, what it handed back) in call order


def _burst_api(method, **params):
    if method == "conversations.history":
        _bx_calls.append((method, _bx_latest[0]))
        return {"messages": [{"ts": _BX_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "burst parent", "reply_count": 3,
                              "latest_reply": _bx_latest[0]}]}
    if method == "conversations.replies":
        msgs = [
            {"ts": _BX_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": _BX_R1, "user": "U0ADA", "subtype": None, "text": "r1"},
            {"ts": _BX_R2, "user": "U0ADA", "subtype": None, "text": "r2"},
            {"ts": _BX_R3, "user": "U0ADA", "subtype": None, "text": "r3"},
        ]
        _bx_calls.append((method, max((m["ts"] for m in msgs), key=float)))
        return {"messages": msgs}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _burst_api
_thread_emitted.clear()
st_bx = {"channel_ts": _BX_PARENT, "baseline_ts": "4000.000000",
         "threads": {_BX_PARENT: _BX_R1}}
w.poll_channel("C_BX", "alerts", st_bx)       # poll 1: history says r2, replies holds r3
# Read after poll 1, not poll 2: by then history reports r3 too, so the cursor
# equals r3 on the unfixed code as well and the check would measure nothing.
_bx_cursor_after_poll1 = st_bx["threads"][_BX_PARENT]
_bx_latest[0] = _BX_R3                        # poll 2: history has caught up to r3
w.poll_channel("C_BX", "alerts", st_bx)
# Measured from what the stub HANDED OUT in poll 1, not from the constants: a
# fixture edited so history already reports r3 at poll 1 keeps every constant
# ordered and turns the burst checks green on the unfixed code - this reds it.
_bx_poll1 = _bx_calls[:2]
check("REGIME CONTROL: in poll 1 the replies call returned a reply newer than history's latest_reply",
      [m for m, _v in _bx_poll1] == ["conversations.history", "conversations.replies"]
      and float(_bx_poll1[0][1]) < float(_bx_poll1[1][1]), f"poll 1 calls={_bx_poll1}")
check("a reply burst is emitted exactly once across two consecutive polls",
      _thread_emitted == [("r2", _BX_PARENT), ("r3", _BX_PARENT)], f"emitted={_thread_emitted}")
check("the thread cursor is the newest reply READ, not history's latest_reply",
      _bx_cursor_after_poll1 == _BX_R3, f"cursor after poll 1={_bx_cursor_after_poll1}")
check("a caught-up thread costs no replies call on the next poll",
      [m for m, _v in _bx_calls].count("conversations.replies") == 1, f"calls={_bx_calls}")

# 10x-ii. A FULL PAGE: the cursor stops at the newest reply READ, never at
#      `latest_reply`, which names replies past the page that nobody read.
#      `conversations.replies` returns the earliest messages after `oldest`
#      first (Slack's own method reference), so a `has_more` page holds the
#      OLDEST unread replies, and the rest are still unread when the call
#      returns. A cursor at the newest one read lets the next poll fetch the
#      rest; a cursor at `latest_reply` drops them for good. This stub honours
#      `oldest` and pages two at a time, because paging is the subject here.
#      Mutation it reds: `max(latest_reply, newest read)` with no page test.
_PG_PARENT = "6000.000000"
_PG_REPLIES = [f"600{i}.000000" for i in range(1, 6)]   # five unread replies
_PG_LIMIT = 2


def _paged_replies_api(method, **params):
    if method == "conversations.history":
        return {"messages": [{"ts": _PG_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "busy parent", "reply_count": 5,
                              "latest_reply": _PG_REPLIES[-1]}]}
    if method == "conversations.replies":
        unread = [t for t in _PG_REPLIES if float(t) > float(params["oldest"])]
        page = unread[:_PG_LIMIT]
        return {"messages": [{"ts": _PG_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "parent"}]
                + [{"ts": t, "user": "U0ADA", "subtype": None, "text": t} for t in page],
                "has_more": len(unread) > _PG_LIMIT}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _paged_replies_api
_thread_emitted.clear()
st_pg = {"channel_ts": _PG_PARENT, "baseline_ts": "4000.000000", "threads": {}}
w.poll_channel("C_PG", "alerts", st_pg)
check("full replies page: the cursor is the newest reply read, not latest_reply",
      st_pg["threads"][_PG_PARENT] == _PG_REPLIES[_PG_LIMIT - 1], f"threads={st_pg['threads']}")
for _ in range(3):
    w.poll_channel("C_PG", "alerts", st_pg)
check("full replies page: later polls deliver the rest, each reply exactly once",
      [t for t, _p in _thread_emitted] == _PG_REPLIES, f"emitted={_thread_emitted}")

# 10x-iii. A `latest_reply` the replies call does not return (the reply was
#      deleted between the calls, or history is ahead of replies) on a page that
#      is NOT full: the cursor still advances to `latest_reply`. Stopping at the
#      newest reply read here would leave `latest_reply > cursor` for good, and
#      every 5s poll would spend a `conversations.replies` call on that thread
#      for the life of the cursor file - a rate-limit leak that ends in a deaf
#      watcher. Mutation it reds: "newest reply read" with no `latest_reply` term.
_ST_PARENT = "7000.000000"
_ST_GONE = "7002.000000"    # history's latest_reply; replies no longer returns it
_st_calls = []


def _stale_latest_api(method, **params):
    _st_calls.append(method)
    if method == "conversations.history":
        return {"messages": [{"ts": _ST_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "parent", "reply_count": 1, "latest_reply": _ST_GONE}]}
    if method == "conversations.replies":
        return {"messages": [
            {"ts": _ST_PARENT, "user": "U0ADA", "subtype": None, "text": "parent"},
            {"ts": "7001.000000", "user": "U0ADA", "subtype": None, "text": "kept"},
        ], "has_more": False}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _stale_latest_api
_thread_emitted.clear()
st_st = {"channel_ts": _ST_PARENT, "baseline_ts": "4000.000000", "threads": {}}
w.poll_channel("C_ST", "alerts", st_st)
w.poll_channel("C_ST", "alerts", st_st)
check("a latest_reply the replies call omits still advances the cursor (no refetch loop)",
      st_st["threads"][_ST_PARENT] == _ST_GONE
      and _st_calls.count("conversations.replies") == 1
      and _thread_emitted == [("kept", _ST_PARENT)],
      f"threads={st_st['threads']} calls={_st_calls} emitted={_thread_emitted}")

# 10x-iv. A FAILED replies call advances nothing: the exception reaches main()'s
#      per-conversation guard with this thread's cursor where it was, so the
#      next poll re-reads the same replies.
def _replies_boom_api(method, **params):
    if method == "conversations.history":
        return {"messages": [{"ts": _BX_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "parent", "reply_count": 3, "latest_reply": _BX_R3}]}
    raise w.SlackApiError("conversations.replies", "ratelimited")


w.api = _replies_boom_api
st_boom = {"channel_ts": _BX_PARENT, "baseline_ts": "4000.000000",
           "threads": {_BX_PARENT: _BX_R1}}
try:
    w.poll_channel("C_BOOM", "alerts", st_boom)
    _boom_raised = False
except w.SlackApiError:
    _boom_raised = True
check("a failed replies call propagates and leaves the thread cursor unmoved",
      _boom_raised and st_boom["threads"] == {_BX_PARENT: _BX_R1}, f"state={st_boom}")

# 10x-v. A `has_more` page that read NOTHING past the cursor. Slack documents
#      that a page may come back shorter than `limit` before the end, so a page
#      holding only the parent with `has_more` set is a shape the API permits.
#      Stopping at "the newest reply read" there leaves the cursor where it was,
#      `latest_reply` stays ahead of it, and every 5s poll re-issues the same
#      call for good, with no line - so that page falls through to the
#      `latest_reply` rule instead. Mutation it reds: dropping
#      `newest_read != seen` from the `has_more` branch.
_EP_PARENT = "8000.000000"
_EP_LATEST = "8003.000000"
_ep_calls = []


def _empty_has_more_api(method, **params):
    _ep_calls.append(method)
    if method == "conversations.history":
        return {"messages": [{"ts": _EP_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "parent", "reply_count": 3, "latest_reply": _EP_LATEST}]}
    if method == "conversations.replies":
        return {"messages": [{"ts": _EP_PARENT, "user": "U0ADA", "subtype": None,
                              "text": "parent"}], "has_more": True}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _empty_has_more_api
st_ep = {"channel_ts": _EP_PARENT, "baseline_ts": "4000.000000", "threads": {}}
for _ in range(3):
    w.poll_channel("C_EP", "alerts", st_ep)
check("a has_more page with nothing past the cursor does not refetch every poll",
      st_ep["threads"].get(_EP_PARENT) == _EP_LATEST
      and _ep_calls.count("conversations.replies") == 1,
      f"threads={st_ep['threads']} calls={_ep_calls}")

w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _emitted.append(
    (channel_name, msg["text"]))   # restore the section's emit stub

# === 10y. OFF-PAGE THREADS, THE SWEEP, THE PAGED POLL ===========================
# The normal poll reads the newest 50 top-level messages, and a thread reply is
# visible only through its parent's `latest_reply`. A thread whose parent has
# more than 50 newer top-level posts above it is therefore invisible to the
# poll, however recent its replies: a human's `yes` in a thread with 52 newer
# posts above its parent is never delivered by the poll at all. These cases pin
# the three mechanisms that close it -
# the SWEEP (every `SWEEP_SECS`, history paged from the poll's page edge back to
# the window start, and a replies call only where `latest_reply` moved past the
# thread's cursor), the PAGED POLL (history paged back to the channel cursor,
# never further than the window), and the SWEEP FLOOR (`sweep_floor_ts`: no
# off-page read reaches below the moment this file was first polled by a
# watcher that sweeps, so the backlog the one-page poll already dropped is not
# replayed when the sweep arrives).
#
# The fake below is a conversation as Slack serves it: history newest-first,
# bounded by `latest`/`oldest` (exclusive unless `inclusive=true`) and paged by
# `next_cursor` - except that a call bounded by `oldest` ALONE returns the
# `limit` OLDEST messages after it (still listed newest-first, `has_more` set
# when newer ones remain), which is what Slack does (measured 2026-11-04)
# and what first sight's window read meets. Every parent carries the
# `reply_count`/`latest_reply` its replies imply. Its replies call IGNORES
# `oldest` unless a case asks otherwise, for the 10t reason: suppression must
# come from the watcher's cursor arithmetic, never from the fake pretending
# Slack filtered.
_YN = time.time()
_DAY = 86400.0
_WINDOW = 7 * _DAY          # the window the ruling sets; w.WINDOW_SECS is its one spelling
_HUMAN = "U0ADA"


def _ago(secs):
    return f"{_YN - secs:.6f}"


def _msg(ts, text, user=_HUMAN):
    return {"ts": ts, "user": user, "subtype": None, "text": text}


class _FakeSlack:
    def __init__(self, top, threads=None, honour_oldest=False, fail=None):
        self.top = list(top)
        self.threads = {p: list(r) for p, r in (threads or {}).items()}
        self.honour_oldest = honour_oldest
        self.fail = dict(fail or {})   # method -> exception factory, raised ONCE
        self.calls = []                # (method, params, what it handed back)

    def _with_thread(self, m):
        reps = self.threads.get(m["ts"])
        if not reps:
            return dict(m)
        return dict(m, reply_count=len(reps),
                    latest_reply=max((r["ts"] for r in reps), key=float))

    def __call__(self, method, **params):
        if method in self.fail:
            self.calls.append((method, dict(params), "RAISED"))
            raise self.fail.pop(method)()
        if method == "conversations.history":
            inc = params.get("inclusive") == "true"
            lat, old = params.get("latest"), params.get("oldest")

            def inside(ts):
                f = float(ts)
                if lat is not None and (f > float(lat) or (f == float(lat) and not inc)):
                    return False
                if old is not None and (f < float(old) or (f == float(old) and not inc)):
                    return False
                return True
            msgs = [self._with_thread(m) for m in
                    sorted(self.top, key=lambda m: -float(m["ts"])) if inside(m["ts"])]
            start, limit = int(params.get("cursor") or 0), int(params.get("limit", 100))
            if old is not None and lat is None:
                asc = msgs[::-1]                       # the oldest after `oldest` first
                page = asc[start:start + limit][::-1]  # ...listed newest-first
            else:
                page = msgs[start:start + limit]
            out = {"messages": page, "has_more": start + limit < len(msgs)}
            if out["has_more"]:
                out["response_metadata"] = {"next_cursor": str(start + limit)}
            self.calls.append((method, dict(params), [m["ts"] for m in page]))
            return out
        if method == "conversations.replies":
            parent = next(m for m in self.top if m["ts"] == params["ts"])
            reps = sorted(self.threads.get(params["ts"], []), key=lambda r: float(r["ts"]))
            if self.honour_oldest:
                reps = [r for r in reps if float(r["ts"]) > float(params["oldest"])]
            self.calls.append((method, dict(params), [r["text"] for r in reps]))
            return {"messages": [self._with_thread(parent)] + reps, "has_more": False}
        raise AssertionError(f"unexpected api call {method} {params}")

    def n(self, method, **match):
        return sum(1 for m, p, _ in self.calls
                   if m == method and all(p.get(k) == v for k, v in match.items()))


_off_emitted = []
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _off_emitted.append(
    (msg["text"], parent_ts))


def _sweep(fake, cid, state, edge, is_dm=False):
    """Run a whole sweep from `edge` against `fake` with no budget, or do nothing
    where the module has none - so an unswept tree REDS these checks instead of
    crashing the file."""
    w.api = fake
    pos = w.new_sweep(edge) if hasattr(w, "new_sweep") else None
    if pos is not None:
        w.sweep_channel(cid, "general", state, pos, is_dm=is_dm)


def _poll(fake, cid, state, is_dm=False):
    w.api = fake
    return w.poll_channel(cid, "general", state, is_dm=is_dm)


# 60 top-level posts in the last hour: the newest-50 page holds none older.
_CHATTER = [_msg(_ago(600 + 50 * i), f"chatter {i}") for i in range(60)]
_NEWEST = max((m["ts"] for m in _CHATTER), key=float)

# 10y-i. A TRACKED thread whose parent is OFF the page: its new reply is read by
#      the sweep from the thread's own cursor. Regime control: the poll alone
#      delivers nothing and its page really did not hold the parent.
_P = _ago(2 * _DAY)
_P_R1 = _ago(1.5 * _DAY)    # already read: the stored thread cursor
_P_YES = _ago(60)           # the reply the one-page poll could never see
_fk = _FakeSlack(_CHATTER + [_msg(_P, "thread parent, two days old")],
                 {_P: [_msg(_P_R1, "earlier reply"), _msg(_P_YES, "yes")]})
_st_a = {"channel_ts": _NEWEST, "baseline_ts": _ago(6 * _DAY),
         "sweep_floor_ts": _ago(_DAY), "threads": {_P: _P_R1}}
_off_emitted.clear()
_edge_a = _poll(_fk, "C_OFF", _st_a)
_page_a = _fk.calls[0][2]
check("REGIME CONTROL: the poll's own page does not hold the off-page parent, and the poll alone delivers nothing",
      _P not in _page_a and len(_page_a) == 50 and _off_emitted == [],
      f"page holds parent={_P in _page_a} size={len(_page_a)} emitted={_off_emitted}")
_sweep(_fk, "C_OFF", _st_a, _edge_a)
check("10y-i. an off-page TRACKED thread's new reply is delivered by the sweep",
      _off_emitted == [("yes", _P)], f"emitted={_off_emitted}")
check("10y-i. the off-page thread's cursor advances to the reply it read",
      _st_a["threads"].get(_P) == _P_YES, f"threads={_st_a['threads']}")
_n_rep = _fk.n("conversations.replies")
_off_emitted.clear()
_sweep(_fk, "C_OFF", _st_a, _poll(_fk, "C_OFF", _st_a))
check("10y-i. a caught-up off-page thread costs no replies call and emits nothing on the next sweep",
      _fk.n("conversations.replies") == _n_rep and _off_emitted == [],
      f"replies calls {_n_rep}->{_fk.n('conversations.replies')} emitted={_off_emitted}")

# 10y-ii. The gap per-thread tracking alone cannot see: a thread whose FIRST
#      reply comes after its parent left the page - here the bot answers an old
#      post and then a human answers the bot. It is in no `threads` entry, so only
#      the parent's `latest_reply`, read by the sweep, can find it. The bot's own
#      reply advances the cursor and is not delivered. A second untracked thread
#      whose replies all predate the sweep floor costs no call and emits nothing.
_Q = _ago(3 * _DAY)
_Q_BOT = _ago(300)
_Q_HUMAN = _ago(120)
_R = _ago(4 * _DAY)
_fk = _FakeSlack(_CHATTER + [_msg(_Q, "old post"), _msg(_R, "older post")],
                 {_Q: [_msg(_Q_BOT, "bot answers an old post", user=BOT),
                       _msg(_Q_HUMAN, "human answers the bot")],
                  _R: [_msg(_ago(2 * _DAY), "reply from before the sweep floor")]})
_st_b = {"channel_ts": _NEWEST, "baseline_ts": _ago(6 * _DAY),
         "sweep_floor_ts": _ago(_DAY), "threads": {}}
_off_emitted.clear()
_sweep(_fk, "C_GAP", _st_b, _poll(_fk, "C_GAP", _st_b))
check("10y-ii. the first reply after the parent left the page is delivered; the bot's own is not",
      _off_emitted == [("human answers the bot", _Q)], f"emitted={_off_emitted}")
check("10y-ii. that thread is tracked from the newest reply read",
      _st_b["threads"].get(_Q) == _Q_HUMAN, f"threads={_st_b['threads']}")
check("10y-ii. an untracked off-page thread with nothing past the sweep floor costs no replies call",
      _fk.n("conversations.replies", ts=_R) == 0 and _R not in _st_b["threads"],
      f"calls for R={_fk.n('conversations.replies', ts=_R)} threads={_st_b['threads']}")

# 10y-iii. NO REPLAY of the backlog the one-page poll already dropped. The shape
#      is the measured one: a tracked thread whose cursor stopped when its parent
#      left the page, with replies after that cursor and before the sweep floor.
#      Those replies are not delivered by the sweep - not on its first pass (no
#      call at all: `latest_reply` is below the floor) and not on a later pass
#      that a NEW reply triggers, although the fake hands the backlog back in
#      that call. The `oldest` the call carries is asserted separately, so the
#      cursor arithmetic and the request cannot cover for each other.
_T = _ago(2 * _DAY)
_T_CURSOR = _ago(1.9 * _DAY)
_T_FLOOR = _ago(_DAY)
_backlog = [_msg(_ago(1.8 * _DAY), "backlog one"), _msg(_ago(1.5 * _DAY), "backlog two")]
_fk = _FakeSlack(_CHATTER + [_msg(_T, "stuck thread")], {_T: list(_backlog)})
_st_c = {"channel_ts": _NEWEST, "baseline_ts": _ago(6 * _DAY),
         "sweep_floor_ts": _T_FLOOR, "threads": {_T: _T_CURSOR}}
_off_emitted.clear()
_sweep(_fk, "C_STUCK", _st_c, _poll(_fk, "C_STUCK", _st_c))
check("10y-iii. the dropped backlog below the sweep floor costs no call, emits nothing, and leaves the cursor alone",
      _fk.n("conversations.replies") == 0 and _off_emitted == []
      and _st_c["threads"][_T] == _T_CURSOR,
      f"replies calls={_fk.n('conversations.replies')} emitted={_off_emitted} threads={_st_c['threads']}")
_fk.threads[_T].append(_msg(_ago(30), "new after the upgrade"))
_sweep(_fk, "C_STUCK", _st_c, _poll(_fk, "C_STUCK", _st_c))
_rep_calls = [(p, got) for m, p, got in _fk.calls if m == "conversations.replies"]
check("10y-iii. REGIME CONTROL: the replies call handed the backlog back, so its suppression is the watcher's",
      len(_rep_calls) == 1 and "backlog one" in _rep_calls[0][1], f"replies calls={_rep_calls}")
check("10y-iii. a new reply is delivered and the backlog is not",
      _off_emitted == [("new after the upgrade", _T)], f"emitted={_off_emitted}")
check("10y-iii. the off-page read starts at the sweep floor, not at the stale cursor",
      len(_rep_calls) == 1 and _rep_calls[0][0].get("oldest") == _T_FLOOR,
      f"oldest={[p.get('oldest') for p, _ in _rep_calls]} floor={_T_FLOOR}")

# 10y-iv. A LEGACY state file (neither `baseline_ts` nor `sweep_floor_ts`) gets
#      its sweep floor from its first poll - "now" - so the upgrade replays
#      nothing; `baseline_ts` is still never written into it (10u's invariant).
_fk = _FakeSlack(_CHATTER + [_msg(_T, "stuck thread")], {_T: list(_backlog)})
_st_l = {"channel_ts": _NEWEST, "threads": {_T: _T_CURSOR}}
_off_emitted.clear()
_sweep(_fk, "C_LEG", _st_l, _poll(_fk, "C_LEG", _st_l))
check("10y-iv. a legacy file's first poll writes sweep_floor_ts = now",
      float(_st_l.get("sweep_floor_ts") or 0) >= _YN, f"state={_st_l}")
check("10y-iv. a legacy file replays no backlog on upgrade and gains no baseline_ts",
      _off_emitted == [] and "baseline_ts" not in _st_l, f"emitted={_off_emitted} state={_st_l}")

# 10y-v. THE WINDOW. A tracked thread whose parent is older than the window and
#      whose newest reply read is older than it too is not polled at all - the
#      residual bound, deliberately: a reply there is not read. One whose parent
#      is older than the window but whose newest reply read is inside it costs
#      exactly one replies call per sweep (history cannot list a parent that
#      old), and its new reply is delivered. The sweep's history read stops at
#      the window start.
_O1, _O2, _O3 = _ago(10 * _DAY), _ago(10 * _DAY - 1), _ago(10 * _DAY - 2)
_fk = _FakeSlack(_CHATTER + [_msg(_O1, "ancient parent, quiet thread"),
                             _msg(_O2, "ancient parent, live thread"),
                             _msg(_O3, "ancient parent, nothing new")],
                 {_O1: [_msg(_ago(8 * _DAY), "o1 old"), _msg(_ago(60), "o1 revived")],
                  _O2: [_msg(_ago(3 * _DAY), "o2 recent"), _msg(_ago(60), "o2 new")],
                  _O3: [_msg(_ago(3 * _DAY), "o3 recent")]})
_st_d = {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
         "threads": {_O1: _ago(8 * _DAY), _O2: _ago(3 * _DAY), _O3: _ago(3 * _DAY)}}
_off_emitted.clear()
_sweep(_fk, "C_WIN", _st_d, _poll(_fk, "C_WIN", _st_d))
check("10y-v. a thread whose parent AND newest read reply are older than the window is not polled",
      _fk.n("conversations.replies", ts=_O1) == 0 and ("o1 revived", _O1) not in _off_emitted,
      f"calls={_fk.n('conversations.replies', ts=_O1)} emitted={_off_emitted}")
check("10y-v. an old parent with a reply read inside the window costs one call and delivers its new reply",
      _fk.n("conversations.replies", ts=_O2) == 1 and _off_emitted == [("o2 new", _O2)],
      f"calls={_fk.n('conversations.replies', ts=_O2)} emitted={_off_emitted}")
check("10y-v. a read that finds nothing new leaves the cursor where it was, not at the floor it started from",
      _fk.n("conversations.replies", ts=_O3) == 1 and _st_d["threads"][_O3] == _ago(3 * _DAY),
      f"calls={_fk.n('conversations.replies', ts=_O3)} cursor={_st_d['threads'][_O3]}")
_sweep_hist = [p for m, p, _ in _fk.calls if m == "conversations.history" and "latest" in p]
check("10y-v. the sweep's history read stops at the 7-day window start",
      len(_sweep_hist) >= 1
      and all(abs(float(p["oldest"]) - (_YN - _WINDOW)) < 60 for p in _sweep_hist),
      f"sweep history calls={_sweep_hist}")

# 10y-vi. THE CATCH-UP. After downtime, 120 new top-level messages arrived; the
#      poll reads forward from the channel cursor and delivers every one, once,
#      in order. One page of 50 would have dropped 70 of them for good. The
#      catch-up keeps messages from the cursor ON (`>= start`), the cursor's own
#      message included, so that message's thread is read by the catch-up itself
#      - delivered once, never repeating the message - and the same cycle's
#      sweep, which starts below the cursor, adds nothing.
_old5 = [_msg(_ago(5 * _DAY + i), f"seen {i}") for i in range(5)]
_new120 = [_msg(_ago(7200 - 50 * i), f"downtime {i:03d}") for i in range(120)]
_AT_CURSOR = _old5[0]["ts"]   # the newest message the poll had read: the channel cursor itself
_fk = _FakeSlack(_old5 + _new120, {_AT_CURSOR: [_msg(_ago(3000), "reply under the cursor's own message")]})
_st_e = {"channel_ts": max((m["ts"] for m in _old5), key=float),
         "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(30 * _DAY), "threads": {}}
check("REGIME CONTROL: the message at the old cursor is the one the fixture threads",
      _AT_CURSOR == _st_e["channel_ts"])
_off_emitted.clear()
_st_e_edge = _poll(_fk, "C_DOWN", _st_e)
check("10y-vi. every top-level message since the cursor is delivered once, in order",
      [t for t, p in _off_emitted if p is None] == [f"downtime {i:03d}" for i in range(120)],
      f"emitted {len(_off_emitted)}: first={_off_emitted[:1]} last={_off_emitted[-1:]}")
check("10y-vi. the channel cursor ends at the newest message",
      _st_e["channel_ts"] == _new120[-1]["ts"], f"channel_ts={_st_e['channel_ts']}")
check("10y-vi. the catch-up stops at the cursor: one page of 50 plus one chunk",
      _fk.n("conversations.history") == 2, f"history calls={_fk.n('conversations.history')}")
_sweep(_fk, "C_DOWN", _st_e, _st_e_edge)
check("10y-vi. the cursor message's thread is read by the catch-up (>= start), once; the sweep adds nothing",
      [x for x in _off_emitted if x[1] is not None] == [("reply under the cursor's own message", _AT_CURSOR)]
      and _off_emitted.count(("seen 0", None)) == 0, f"emitted={[x for x in _off_emitted if x[1]]}")

# 10y-vii. THE CAP. A cursor older than the window pages back no further than the
#      window start; what lies between the two is not read, and ONE WATCH-INFO
#      line says so - the next poll says nothing more.
_pre = [_msg(_ago(8 * _DAY + 60 * i), f"pre-window {i}") for i in range(5)]
_in80 = [_msg(_ago(6 * _DAY - 600 * i), f"in-window {i:02d}") for i in range(80)]
_fk = _FakeSlack(_pre + _in80)
_st_f = {"channel_ts": _ago(9 * _DAY), "baseline_ts": _ago(30 * _DAY),
         "sweep_floor_ts": _ago(30 * _DAY), "threads": {}}
check("10y-vii. REGIME CONTROL: posts really exist between the cursor and the window start",
      all(float(_st_f["channel_ts"]) < float(m["ts"]) < _YN - _WINDOW for m in _pre))
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_CAP", _st_f)
_cap1 = [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-INFO")]
check("10y-vii. a cursor past the window delivers the in-window messages and none older",
      [t for t, _p in _off_emitted] == [f"in-window {i:02d}" for i in range(80)],
      f"emitted {len(_off_emitted)}: {_off_emitted[:2]}")
check("10y-vii. the cap is announced by ONE WATCH-INFO line naming the conversation",
      len(_cap1) == 1 and "C_CAP" in _cap1[0], f"info={_cap1}")
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_CAP", _st_f)
check("10y-vii. the next poll says nothing more",
      "WATCH-INFO" not in _buf.getvalue(), f"stderr={_buf.getvalue()!r}")

# 10y-viii. STEADY STATE costs what the one-page poll cost. A caught-up busy
#      conversation (410 top-level posts in the window) is ONE history call per
#      poll and no replies call; its sweep pages the 360 posts below the page
#      edge (exclusive: the edge is on the page) back to the window start in
#      ceil(360/200) = 2 calls, where a
#      sweep that ignored the edge and re-read the page would need 3 - the count
#      is chosen so the two differ. A quiet conversation whose page reaches its
#      start costs the sweep NOTHING.
_busy = [_msg(_ago(6 * _DAY - 1260 * i), f"busy {i}") for i in range(410)]
_fk = _FakeSlack(_busy)
_st_g = {"channel_ts": max((m["ts"] for m in _busy), key=float),
         "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY), "threads": {}}
_off_emitted.clear()
_edge_g = _poll(_fk, "C_BUSY", _st_g)
check("10y-viii. a caught-up poll is one history call of 50 and no replies call",
      _fk.calls and [(m, p.get("limit")) for m, p, _ in _fk.calls] == [("conversations.history", 50)],
      f"calls={[(m, p) for m, p, _ in _fk.calls]}")
_n0 = len(_fk.calls)
_sweep(_fk, "C_BUSY", _st_g, _edge_g)
check("10y-viii. the sweep of 360 off-page posts is two history pages from the page edge, no replies call",
      [m for m, _p, _ in _fk.calls[_n0:]] == ["conversations.history"] * 2
      and _fk.calls[_n0][1].get("latest") == _edge_g,
      f"edge={_edge_g} sweep calls={[(m, p) for m, p, _ in _fk.calls[_n0:]]}")
_fk = _FakeSlack([_msg(_ago(3600 * i), f"dm {i}") for i in range(10)])
_st_q = {"channel_ts": _ago(0), "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
         "threads": {}}
_edge_q = _poll(_fk, "D_QUIET", _st_q, is_dm=True)
_n0 = len(_fk.calls)
_sweep(_fk, "D_QUIET", _st_q, _edge_q, is_dm=True)
check("10y-viii. a conversation whose page reaches its start costs the sweep no call",
      _n0 == 1 and len(_fk.calls) == _n0, f"poll calls={_n0} sweep calls={len(_fk.calls) - _n0}")

# 10y-ix. A FAILED CALL MID-POLL DOES NOT RE-SEND. Delivery is decided against
#      `channel_ts`, so it has to advance with every top-level message the poll
#      delivers, not once at the end: main() keeps the same state dict after a
#      failed poll, and a cursor that only moved at the end leaves every message
#      delivered before the failure to be delivered again. The pre-existing form
#      of the watcher did exactly that whenever a replies call raised.
_A, _PP, _PR = _ago(200), _ago(100), _ago(50)
_fk = _FakeSlack([_msg(_ago(400), "old"), _msg(_A, "new top-level"), _msg(_PP, "new parent")],
                 {_PP: [_msg(_PR, "reply")]},
                 fail={"conversations.replies": lambda: w.SlackApiError("conversations.replies",
                                                                        "ratelimited")})
_st_h = {"channel_ts": _ago(300), "baseline_ts": _ago(_DAY), "sweep_floor_ts": _ago(_DAY),
         "threads": {}}
_off_emitted.clear()
try:
    _poll(_fk, "C_MID", _st_h)
    _mid_raised = False
except w.SlackApiError:
    _mid_raised = True
_poll(_fk, "C_MID", _st_h)                    # same dict, exactly as main() keeps it
check("10y-ix. REGIME CONTROL: the first poll really failed mid-way",
      _mid_raised and _fk.n("conversations.replies") == 2, f"raised={_mid_raised} calls={_fk.calls}")
check("10y-ix. a poll that fails mid-way does not re-send what it already delivered",
      _off_emitted == [("new top-level", None), ("new parent", None), ("reply", _PP)],
      f"emitted={_off_emitted}")

# 10y-x. A RATE-LIMITED SWEEP stops at its first refused call and raises it
#      unchanged (main() turns it into one `WATCH-ERROR sweep` line, section 17):
#      no retry of an `ok:false` answer and no further pages, so a sweep adds no
#      pressure to a bucket that is already refusing.
_fk = _FakeSlack(_busy, fail={"conversations.history": lambda: w.SlackApiError(
    "conversations.history", "ratelimited")})
_st_r = dict(_st_g, threads={})
try:
    _sweep(_fk, "C_RL", _st_r, _edge_g)
    _rl_exc = None
except Exception as e:  # noqa: BLE001 - the check reads which exception
    _rl_exc = e
check("10y-x. a rate-limited sweep raises the SlackApiError after ONE call",
      isinstance(_rl_exc, w.SlackApiError) and _rl_exc.code == "ratelimited"
      and len(_fk.calls) == 1, f"exc={_rl_exc!r} calls={len(_fk.calls)}")

# 10y-xi. ROLLBACK SAFETY: the state file gains ONE key and changes no other.
#      The previous watcher loads the dict and rewrites all of it, so an unknown
#      key survives a rollback; a renamed or reshaped one would not. Every value
#      stays a ts string and `threads` stays parent ts -> cursor ts. The state is
#      born here from first sight, so the shape measured is the one this code
#      writes, not one a fixture wrote for it. At first sight the sweep floor is
#      the first-sight baseline itself.
_fk = _FakeSlack(_CHATTER + [_msg(_P, "thread parent, two days old")],
                 {_P: [_msg(_P_R1, "earlier reply"), _msg(_P_YES, "yes")]})
_st_x = {}
_poll(_fk, "C_NEW", _st_x)                    # first sight
_sweep(_fk, "C_NEW", _st_x, _poll(_fk, "C_NEW", _st_x))
_st_x = json.loads(json.dumps(_st_x))
check("10y-xi. first sight sets the sweep floor to the first-sight baseline",
      _st_x.get("sweep_floor_ts") is not None
      and _st_x.get("sweep_floor_ts") == _st_x.get("baseline_ts"), f"state={_st_x}")
check("10y-xi. the state file is the old shape plus sweep_floor_ts, and nothing else",
      set(_st_x) == {"channel_ts", "baseline_ts", "threads", "sweep_floor_ts"}
      and all(isinstance(_st_x[k], str) for k in ("channel_ts", "baseline_ts", "sweep_floor_ts"))
      and all(isinstance(k, str) and isinstance(v, str) for k, v in _st_x["threads"].items()),
      f"state={_st_x}")


# 10y-iv-b. The file shape MOST cursor files have when sweeping begins: a
#      first-sight baseline but no sweep floor. Its first poll sets the floor to
#      "now", NOT to the baseline - the baseline is days or weeks old, and a
#      floor there would deliver the whole dropped backlog on the first sweep.
_fk = _FakeSlack(_CHATTER + [_msg(_T, "stuck thread")], {_T: list(_backlog)})
_st_bb = {"channel_ts": _NEWEST, "baseline_ts": _ago(6 * _DAY), "threads": {_T: _T_CURSOR}}
_off_emitted.clear()
_sweep(_fk, "C_BB", _st_bb, _poll(_fk, "C_BB", _st_bb))
check("10y-iv-b. a file with a baseline and no sweep floor gets the floor at now, not at its baseline",
      float(_st_bb.get("sweep_floor_ts") or 0) >= _YN, f"state={_st_bb}")
check("10y-iv-b. ...and replays no backlog",
      _off_emitted == [], f"emitted={_off_emitted}")


def _calls_by_poll(fake, n0):
    """History calls the fake served since index n0."""
    return [p for m, p, _ in fake.calls[n0:] if m == "conversations.history"]


# 10y-xii. THE CATCH-UP CAP. 650 top-level messages arrived while the watcher was
#      down. The catch-up delivers the NEWEST 200 - recency is what a returning
#      agent needs - in order, once, for TWO history calls (the page and the
#      newest-201 call): nothing is counted. ONE WATCH-INFO line names the
#      conversation, the range from the cursor to the oldest delivered message
#      in ISO UTC, says thread replies there were skipped too, and names the
#      fetch recipe - no count. The sweep floor rises to the oldest delivered
#      message: a reply under a skipped parent posted before it is not
#      delivered, one posted after it is. The cursor ends at the newest message,
#      so the next poll is steady state: one call, no line, nothing repeated.
import datetime as _dt


def _iso_utc(ts):
    return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _calls_by_poll(fake, n0):
    """History calls the fake served since index n0."""
    return [p for m, p, _ in fake.calls[n0:] if m == "conversations.history"]


_old3 = [_msg(_ago(3 * _DAY + i), f"seen {i}") for i in range(3)]
_new650 = [_msg(_ago(20000 - 20 * i), f"backlog {i:03d}") for i in range(650)]
_SK = _new650[100]["ts"]                  # a skipped parent
_KEPT_OLDEST = _new650[450]["ts"]         # the oldest message the cap delivers
_SK_OLD = _ago(20000 - 20 * 300)          # a reply under _SK, before the oldest delivered
_fk = _FakeSlack(_old3 + _new650, {_SK: [_msg(_SK_OLD, "skipped-thread reply before the cap"),
                                         _msg(_ago(30), "skipped-thread reply after the cap")]})
_cursor_k = max((m["ts"] for m in _old3), key=float)
_st_k = {"channel_ts": _cursor_k, "baseline_ts": _ago(30 * _DAY),
         "sweep_floor_ts": _ago(30 * _DAY), "threads": {}}
check("10y-xii. REGIME CONTROL: one reply lies before the oldest delivered message and one after, both past the old floor",
      float(_st_k["sweep_floor_ts"]) < float(_SK_OLD) < float(_KEPT_OLDEST) < _YN - 30)
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _cap_edge1 = _poll(_fk, "C_CATCH", _st_k)
_cap_info = [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]
_cap_calls1 = _fk.n("conversations.history")
check("10y-xii. a 650-post backlog delivers exactly the NEWEST 200, in order, once",
      [t for t, p in _off_emitted if p is None] == [f"backlog {i:03d}" for i in range(450, 650)],
      f"emitted {len(_off_emitted)}: first={_off_emitted[:1]} last={_off_emitted[-1:]}")
check("10y-xii. ONE WATCH-INFO line: the conversation, cursor-to-oldest-delivered in ISO UTC, thread replies, the recipe, no count",
      len(_cap_info) == 1 and _cap_info[0].startswith("WATCH-INFO") and "C_CATCH" in _cap_info[0]
      and f"from {_iso_utc(_cursor_k)} to before {_iso_utc(_KEPT_OLDEST)}" in _cap_info[0]
      and "thread replies" in _cap_info[0] and "Fetch a message / thread" in _cap_info[0]
      and "450" not in _cap_info[0], f"lines={_cap_info}")
check("10y-xii. the catch-up costs exactly two history calls: the page and the newest-201 call",
      _cap_calls1 == 2, f"history calls={_cap_calls1}")
check("10y-xii. the sweep floor rises to the oldest delivered message",
      _st_k["sweep_floor_ts"] == _KEPT_OLDEST, f"floor={_st_k['sweep_floor_ts']} oldest kept={_KEPT_OLDEST}")
_off_emitted.clear()
_sweep(_fk, "C_CATCH", _st_k, _cap_edge1)       # the same cycle's sweep, from the catch-up's edge
check("10y-xii. under a skipped parent the sweep delivers the reply after the cap, once, and not the one before it",
      _off_emitted == [("skipped-thread reply after the cap", _SK)], f"edge={_cap_edge1} emitted={_off_emitted}")
_off_emitted.clear()
_n0 = len(_fk.calls)
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_CATCH", _st_k)
check("10y-xii. the cursor ends past the skipped range: the next poll is one call, silent, and repeats nothing",
      _st_k["channel_ts"] == _new650[-1]["ts"] and len(_calls_by_poll(_fk, _n0)) == 1
      and _off_emitted == [] and "WATCH-" not in _buf.getvalue(),
      f"cursor={_st_k['channel_ts']} calls={len(_calls_by_poll(_fk, _n0))} emitted={_off_emitted[:2]}")

# 10y-xii-d. A 6400-POST OUTAGE costs the catch-up poll exactly TWO history calls
#      and prints one line: nothing is counted, so the cost does not grow with
#      the backlog (a count would be 33 calls in one poll, outside the budget).
_new6400 = [_msg(_ago(90000 - 10 * i), f"big {i:04d}") for i in range(6400)]
_fk = _FakeSlack(_old3 + _new6400)
_st_big = {"channel_ts": _cursor_k, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(30 * _DAY),
           "threads": {}}
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_BIG", _st_big)
check("10y-xii-d. a 6400-post backlog: exactly two history calls, one line, the newest 200 delivered",
      _fk.n("conversations.history") == 2
      and len([ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]) == 1
      and [t for t, p in _off_emitted if p is None] == [f"big {i:04d}" for i in range(6200, 6400)],
      f"calls={_fk.n('conversations.history')} emitted={len(_off_emitted)} stderr={_buf.getvalue()[:160]!r}")

# 10y-xii-e. EXACTLY 200 after the cursor is no skip: all of them delivered, no
#      line, and the sweep floor where it was. (The newest-201 call's extra
#      message is the cursor's own, not a skipped one.)
_new200 = [_msg(_ago(9000 - 10 * i), f"two {i:03d}") for i in range(200)]
_fk = _FakeSlack(_old3 + _new200)
_st_200 = {"channel_ts": _cursor_k, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(30 * _DAY),
           "threads": {}}
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_200", _st_200)
check("10y-xii-e. a backlog of exactly 200 is delivered whole, with no line and the floor unmoved",
      [t for t, p in _off_emitted if p is None] == [f"two {i:03d}" for i in range(200)]
      and "WATCH-" not in _buf.getvalue() and _st_200["sweep_floor_ts"] == _ago(30 * _DAY),
      f"emitted={len(_off_emitted)} stderr={_buf.getvalue()[:160]!r} floor={_st_200['sweep_floor_ts']}")

# 10y-xii-f. THE FLOOR IS NEVER LOWERED: a sweep floor already above the oldest
#      delivered message stays where it was.
_fk = _FakeSlack(_old3 + _new650)
_st_hi = {"channel_ts": _cursor_k, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(10),
          "threads": {}}
with contextlib.redirect_stderr(io.StringIO()):
    _poll(_fk, "C_HIFLOOR", _st_hi)
check("10y-xii-f. a catch-up never lowers the sweep floor",
      _st_hi["sweep_floor_ts"] == _ago(10), f"floor={_st_hi['sweep_floor_ts']}")


class _RefuseNth(_FakeSlack):
    """Raises a rate-limit answer on the Nth history call it is asked for."""
    def __init__(self, *a, refuse_at, **k):
        super().__init__(*a, **k)
        self.refuse_at, self.n_hist = refuse_at, 0

    def __call__(self, method, **params):
        if method == "conversations.history":
            self.n_hist += 1
            if self.n_hist == self.refuse_at:
                self.calls.append((method, dict(params), "RAISED"))
                raise w.SlackApiError("conversations.history", "ratelimited")
        return super().__call__(method, **params)


# 10y-xii-b. A REFUSED newest-200 call delivers nothing, prints no line and moves
#      no cursor; the next poll does the whole catch-up.
_fk = _RefuseNth(_old3 + _new650, refuse_at=2)
_st_k2 = dict(_st_k, channel_ts=max((m["ts"] for m in _old3), key=float), threads={})
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    try:
        _poll(_fk, "C_REFUSED", _st_k2)
        _ref_raised = False
    except w.SlackApiError:
        _ref_raised = True
    _ref_lines1 = [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]
    _ref_cursor = _st_k2["channel_ts"]
    try:
        _poll(_fk, "C_REFUSED", _st_k2)
        _ref2_exc = None
    except Exception as e:  # noqa: BLE001 - a raise is the failure being measured
        _ref2_exc = e
check("10y-xii-b. a refused catch-up delivers nothing, prints nothing and leaves the cursor",
      _ref_raised and _ref_lines1 == [] and _ref_cursor == max((m["ts"] for m in _old3), key=float),
      f"raised={_ref_raised} lines={_ref_lines1} cursor={_ref_cursor}")
check("10y-xii-b. the next poll does the catch-up: the newest 200 and one line",
      _ref2_exc is None
      and [t for t, p in _off_emitted if p is None] == [f"backlog {i:03d}" for i in range(450, 650)]
      and len([ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]) == 1,
      f"emitted={len(_off_emitted)}")

# 10y-xiii-b. THE CAPPED CATCH-UP DELIVERS ONLY WHAT IT SAYS IT READ. A quiet
#      channel whose newest-50 page reaches back past the window, and a cursor
#      older than the window (a bot re-invited weeks later): the messages from
#      before the window start are not delivered - the WATCH-INFO line says they
#      were not read - even though the poll's own page holds them.
_q_pre = [_msg(_ago(8 * _DAY + 600 * i), f"pre-window {i:02d}") for i in range(40)]
_q_in = [_msg(_ago(6 * _DAY - 3600 * i), f"in-window {i:02d}") for i in range(20)]
_fk = _FakeSlack(_q_pre + _q_in)
_st_q2 = {"channel_ts": _ago(20 * _DAY), "baseline_ts": _ago(30 * _DAY),
          "sweep_floor_ts": _ago(30 * _DAY), "threads": {}}
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _poll(_fk, "C_QUIET", _st_q2)
_q_page = _fk.calls[0][2]
check("10y-xiii-b. REGIME CONTROL: the poll's own page holds messages from before the window start",
      sum(1 for t in _q_page if float(t) < _YN - _WINDOW) >= 20, f"page={len(_q_page)}")
check("10y-xiii-b. a capped catch-up delivers the in-window messages and none of the page's older ones",
      [t for t, _p in _off_emitted] == [f"in-window {i:02d}" for i in range(20)],
      f"emitted={[t for t, _p in _off_emitted][:3]}... ({len(_off_emitted)})")


def _try_sweep(fake, cid, state, edge=None, pos=None, **kw):
    """sweep_channel from `pos` (or a new sweep from `edge`), with keyword
    arguments a module may not take yet: a tree without them REDS the check
    instead of crashing the file. Returns (result, exception)."""
    w.api = fake
    try:
        if pos is None:
            pos = w.new_sweep(edge)
            if pos is None:
                return True, None
        return w.sweep_channel(cid, "general", state, pos, **kw), None
    except Exception as e:  # noqa: BLE001
        return None, e


# 10y-xiv. A SWEEP IS RESUMABLE. Given a budget of one call, it stops after one
#      history page and says so, recording where; handed that position back
#      with budget for the rest, it continues from there and reads what it had
#      not yet read, once. The thread fixture sits on the SECOND sweep page, so
#      it is read only after the resume - and its replies call is paid for from
#      the same budget as the page.
_deep = _ago(5.9 * _DAY)
_busy2 = [_msg(_ago(6 * _DAY - 1260 * i), f"busy {i}") for i in range(410)] + [_msg(_deep, "deep parent")]
_fk = _FakeSlack(_busy2, {_deep: [_msg(_ago(90), "deep reply")]})
_st_s = {"channel_ts": max((m["ts"] for m in _busy2), key=float), "baseline_ts": _ago(30 * _DAY),
         "sweep_floor_ts": _ago(_DAY), "threads": {}}
_edge_s = _poll(_fk, "C_RESUME", _st_s)
_pos = w.new_sweep(_edge_s) if hasattr(w, "new_sweep") else None
_off_emitted.clear()
_n0 = len(_fk.calls)
_r1, _e1 = _try_sweep(_fk, "C_RESUME", _st_s, _edge_s, pos=_pos, budget={"left": 1})
_calls1 = len(_calls_by_poll(_fk, _n0))
_emit1 = list(_off_emitted)
_n0 = len(_fk.calls)
_b2 = {"left": 2}
_r2, _e2 = _try_sweep(_fk, "C_RESUME", _st_s, _edge_s, pos=_pos, budget=_b2)
check("10y-xiv. a sweep given one call stops after one history page and reports itself unfinished",
      _e1 is None and _r1 is False and _calls1 == 1 and _emit1 == [],
      f"result={_r1} exc={_e1!r} calls={_calls1} emitted={_emit1}")
check("10y-xiv. handed its position back with two calls it reads page two and the deep thread, once",
      _e2 is None and _r2 is True and len(_calls_by_poll(_fk, _n0)) == 1
      and _fk.n("conversations.replies") == 1 and _b2["left"] == 0
      and _off_emitted == [("deep reply", _deep)],
      f"result={_r2} exc={_e2!r} hist={len(_calls_by_poll(_fk, _n0))} "
      f"replies={_fk.n('conversations.replies')} left={_b2} emitted={_off_emitted}")


class _ThreadFails(_FakeSlack):
    """The replies call for `bad` answers `code`; every other call is served."""
    def __init__(self, *a, bad, code, **k):
        super().__init__(*a, **k)
        self.bad, self.code = bad, code

    def __call__(self, method, **params):
        if method == "conversations.replies" and params.get("ts") == self.bad:
            self.calls.append((method, dict(params), "RAISED"))
            raise w.SlackApiError("conversations.replies", self.code)
        return super().__call__(method, **params)


# 10y-xv. ONE GONE THREAD DOES NOT STOP THE SWEEP. Two tracked threads with
#      parents older than the window; the first one's replies call answers
#      `thread_not_found` (its parent was deleted). The second one's reply is
#      still delivered, the gone thread is dropped from `threads` with ONE line,
#      and a later sweep makes no call for it at all. A rate-limit answer is
#      different: it is about the bucket, so it stops the sweep.
_B1, _B2 = _ago(10 * _DAY), _ago(10 * _DAY - 1)
_tf_top = _CHATTER + [_msg(_B1, "deleted-parent thread"), _msg(_B2, "live old thread")]
_tf_thr = {_B1: [_msg(_ago(2 * _DAY), "b1")], _B2: [_msg(_ago(3 * _DAY), "b2 old"), _msg(_ago(60), "b2 new")]}
_fk = _ThreadFails(_tf_top, _tf_thr, bad=_B1, code="thread_not_found")
_st_t = {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
         "threads": {_B1: _ago(3 * _DAY), _B2: _ago(3 * _DAY)}}
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _r_t1, _e_t1 = _try_sweep(_fk, "C_TF", _st_t, _poll(_fk, "C_TF", _st_t))
    _r_t2, _e_t2 = _try_sweep(_fk, "C_TF", _st_t, _poll(_fk, "C_TF", _st_t))
_tf_lines = [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]
check("10y-xv. a gone thread does not stop the sweep: the next thread's reply is delivered once",
      _e_t1 is None and _e_t2 is None and _off_emitted == [("b2 new", _B2)],
      f"exc={_e_t1!r}/{_e_t2!r} emitted={_off_emitted}")
check("10y-xv. the gone thread is dropped from `threads` with ONE line naming it, and never called again",
      _B1 not in _st_t["threads"] and _fk.n("conversations.replies", ts=_B1) == 1
      and len(_tf_lines) == 1 and _B1 in _tf_lines[0] and "thread_not_found" in _tf_lines[0],
      f"threads={sorted(_st_t['threads'])} calls={_fk.n('conversations.replies', ts=_B1)} "
      f"lines={_tf_lines}")
_fk = _ThreadFails(_tf_top, _tf_thr, bad=_B1, code="ratelimited")
_st_t2 = dict(_st_t, threads={_B1: _ago(3 * _DAY), _B2: _ago(3 * _DAY)})
_off_emitted.clear()
_r_t3, _e_t3 = _try_sweep(_fk, "C_TF2", _st_t2, _poll(_fk, "C_TF2", _st_t2))
check("10y-xv. a rate-limit answer on a thread stops the sweep (it is about the bucket, not the thread)",
      isinstance(_e_t3, w.SlackApiError) and _e_t3.code == "ratelimited" and _off_emitted == [],
      f"exc={_e_t3!r} emitted={_off_emitted}")


class _ThreadRaises(_FakeSlack):
    """The replies call for `bad` raises whatever `make()` builds, `times` times."""
    def __init__(self, *a, bad, make, times=10**9, **k):
        super().__init__(*a, **k)
        self.bad, self.make, self.times = bad, make, times

    def __call__(self, method, **params):
        if method == "conversations.replies" and params.get("ts") == self.bad and self.times:
            self.times -= 1
            self.calls.append((method, dict(params), "RAISED"))
            raise self.make()
        return super().__call__(method, **params)


# HTTP 429 - the form Slack's rate limit actually takes, raised by urlopen before
# any body is read - and a service-wide Slack code both stop the sweep too:
# neither is about the one thread.
for _label, _make in (("an HTTP 429", lambda: urllib.error.HTTPError(
                           "https://slack.com/api/conversations.replies", 429, "Too Many Requests",
                           {}, None)),
                      ("internal_error", lambda: w.SlackApiError("conversations.replies",
                                                                 "internal_error"))):
    _fk = _ThreadRaises(_tf_top, _tf_thr, bad=_B1, make=_make)
    _st_t4 = dict(_st_t, threads={_B1: _ago(3 * _DAY), _B2: _ago(3 * _DAY)})
    _off_emitted.clear()
    _r_t4, _e_t4 = _try_sweep(_fk, "C_TF4", _st_t4, _poll(_fk, "C_TF4", _st_t4))
    check(f"10y-xv. {_label} on one thread stops the sweep instead of being skipped",
          _e_t4 is not None and _off_emitted == [], f"exc={_e_t4!r} emitted={_off_emitted}")

# 10y-xv-b. THE OLD-PARENT STEP RESUMES after the last thread it finished: a
#      rate limit on the second of three such threads, then the same position
#      handed back - the first thread is not called again.
_B3 = _ago(10 * _DAY - 2)
_fk = _ThreadRaises(_tf_top + [_msg(_B3, "third old thread")],
                    {_B1: [_msg(_ago(60), "b1 new")], _B2: [_msg(_ago(50), "b2 new")],
                     _B3: [_msg(_ago(40), "b3 new")]},
                    bad=_B2, times=1, make=lambda: w.SlackApiError("conversations.replies", "ratelimited"))
_st_t5 = {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
          "threads": {_B1: _ago(3 * _DAY), _B2: _ago(3 * _DAY), _B3: _ago(3 * _DAY)}}
_edge_t5 = _poll(_fk, "C_TF5", _st_t5)
_pos5 = w.new_sweep(_edge_t5) if hasattr(w, "new_sweep") else None
_off_emitted.clear()
_r5a, _e5a = _try_sweep(_fk, "C_TF5", _st_t5, _edge_t5, pos=_pos5)
_r5b, _e5b = _try_sweep(_fk, "C_TF5", _st_t5, _edge_t5, pos=_pos5)
check("10y-xv-b. a resumed old-parent step does not call the threads it already finished",
      isinstance(_e5a, w.SlackApiError) and _e5b is None
      and _fk.n("conversations.replies", ts=_B1) == 1
      and _off_emitted == [("b1 new", _B1), ("b2 new", _B2), ("b3 new", _B3)],
      f"exc={_e5a!r}/{_e5b!r} b1 calls={_fk.n('conversations.replies', ts=_B1)} emitted={_off_emitted}")

# 10y-xv-c. A HISTORY-PASS THREAD THAT ANSWERS thread_not_found KEEPS ITS CURSOR.
#      Its parent is still listed, so every sweep reaches it again: forgetting
#      it would repeat the line every sweep, and on an answer that turned out
#      transient would read it again from the floor and re-send replies already
#      delivered. So it is reported once per process and its cursor kept; the
#      sweep goes on to the next thread. (Only the old-parent pass forgets a
#      thread - 10y-xv - because nothing else would ever list it again.)
_HT, _HU = _ago(2 * _DAY), _ago(2 * _DAY - 1)
_HR1 = _ago(1.5 * _DAY)                    # already delivered: the stored cursor
_ht_top = _CHATTER + [_msg(_HT, "listed parent, thread answers not found"), _msg(_HU, "listed parent, live")]
_ht_thr = {_HT: [_msg(_HR1, "already delivered"), _msg(_ago(60), "ht new")],
           _HU: [_msg(_ago(50), "hu new")]}
_ht_state = lambda: {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(3 * _DAY),
                     "threads": {_HT: _HR1}}
check("10y-xv-c. REGIME CONTROL: the floor sits below the delivered reply, so a forgotten cursor would re-send it",
      float(_ht_state()["sweep_floor_ts"]) < float(_HR1))
_fk = _ThreadRaises(_ht_top, _ht_thr, bad=_HT,
                    make=lambda: w.SlackApiError("conversations.replies", "thread_not_found"))
_st_h1 = _ht_state()
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _rh1, _eh1 = _try_sweep(_fk, "C_HT1", _st_h1, _poll(_fk, "C_HT1", _st_h1))
    _rh2, _eh2 = _try_sweep(_fk, "C_HT1", _st_h1, _poll(_fk, "C_HT1", _st_h1))
_ht_lines = [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-")]
check("10y-xv-c. a listed parent's thread answering not-found keeps its cursor and is reported ONCE in two sweeps",
      _eh1 is None and _eh2 is None and _st_h1["threads"].get(_HT) == _HR1
      and len(_ht_lines) == 1 and _HT in _ht_lines[0],
      f"exc={_eh1!r}/{_eh2!r} cursor={_st_h1['threads'].get(_HT)} lines={_ht_lines}")
check("10y-xv-c. ...and the sweep goes on to the next thread",
      _off_emitted == [("hu new", _HU)], f"emitted={_off_emitted}")
_fk = _ThreadRaises(_ht_top, _ht_thr, bad=_HT, times=1,
                    make=lambda: w.SlackApiError("conversations.replies", "thread_not_found"))
_st_h2 = _ht_state()
_off_emitted.clear()
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    _try_sweep(_fk, "C_HT2", _st_h2, _poll(_fk, "C_HT2", _st_h2))
    _rh3, _eh3 = _try_sweep(_fk, "C_HT2", _st_h2, _poll(_fk, "C_HT2", _st_h2))
check("10y-xv-c. a not-found answer that turns out transient re-sends nothing: only the new reply arrives",
      _eh3 is None and _off_emitted.count(("ht new", _HT)) == 1
      and ("already delivered", _HT) not in _off_emitted,
      f"exc={_eh3!r} emitted={[e for e in _off_emitted if e[1] == _HT]}")


# 10y-xvi. A CURSOR PAST THE WINDOW WITH NOTHING INSIDE IT. A cursor older than
#      the window, 60 top-level posts after it, none in the last 7 days: the
#      catch-up finds nothing to deliver, says so ONCE, and moves the cursor to
#      the page's newest message, so every later poll is one call and silent.
#      Left where it was, every poll would repeat the catch-up AND its WATCH-INFO
#      line - a non-429 line per poll, the flood that stops the follower.
_old60 = [_msg(_ago(10 * _DAY - 3600 * i), f"old {i:02d}") for i in range(60)]
_fk = _FakeSlack(_old60)
_st_w = {"channel_ts": _ago(20 * _DAY), "baseline_ts": _ago(30 * _DAY),
         "sweep_floor_ts": _ago(30 * _DAY), "threads": {}}
check("10y-xvi. REGIME CONTROL: every post is newer than the cursor and older than the window start",
      all(float(_st_w["channel_ts"]) < float(m["ts"]) < _YN - _WINDOW for m in _old60))
_off_emitted.clear()
_w_info, _w_calls = [], []
for _ in range(5):
    _n0 = len(_fk.calls)
    _buf = io.StringIO()
    with contextlib.redirect_stderr(_buf):
        _poll(_fk, "C_EMPTYWIN", _st_w)
    _w_info += [ln for ln in _buf.getvalue().splitlines() if ln.startswith("WATCH-INFO")]
    _w_calls.append(len(_calls_by_poll(_fk, _n0)))
check("10y-xvi. an empty window is announced ONCE in five polls, and nothing older is delivered",
      len(_w_info) == 1 and _off_emitted == [], f"info={_w_info} emitted={_off_emitted[:2]}")
check("10y-xvi. ...the cursor moves to the page's newest message, so every later poll is ONE call",
      _st_w["channel_ts"] == max((m["ts"] for m in _old60), key=float) and _w_calls == [2, 1, 1, 1, 1],
      f"cursor={_st_w['channel_ts']} calls per poll={_w_calls}")

# 10y-xviii. A PARENT WHOSE REPLIES CALL FAILED IS READ BY THE NEXT CATCH-UP. The
#      catch-up delivers parent P and moves the cursor to it, then P's replies
#      call fails. The next catch-up keeps messages from the cursor ON (its own
#      message included), so P's thread is read then - P itself is not delivered
#      again. From after the cursor, nothing would read that thread until the
#      sweep, whose floor here sits above P's reply.
_pb = [_msg(_ago(7200 - 50 * i), f"pb {i:03d}") for i in range(120)]
_P = _pb[50]["ts"]
_fk = _ThreadRaises(_old3 + _pb, {_P: [_msg(_ago(3000), "p reply")]}, bad=_P, times=1,
                    make=lambda: w.SlackApiError("conversations.replies", "ratelimited"))
_st_p = {"channel_ts": max((m["ts"] for m in _old3), key=float), "baseline_ts": _ago(30 * _DAY),
         "sweep_floor_ts": _ago(10), "threads": {}}
check("10y-xviii. REGIME CONTROL: the sweep floor sits above P's reply, so the sweep cannot deliver it",
      float(_st_p["sweep_floor_ts"]) > _YN - 3000)
_off_emitted.clear()
try:
    _poll(_fk, "C_PFAIL", _st_p)
    _p_raised = False
except w.SlackApiError:
    _p_raised = True
_p_cursor = _st_p["channel_ts"]
try:
    _poll(_fk, "C_PFAIL", _st_p)
    _p2_exc = None
except Exception as e:  # noqa: BLE001 - a raise is the failure being measured
    _p2_exc = e
check("10y-xviii. REGIME CONTROL: the first poll failed at P's replies call with the cursor on P",
      _p_raised and _p_cursor == _P, f"raised={_p_raised} cursor={_p_cursor} P={_P}")
check("10y-xviii. the next catch-up reads P's thread: its reply is delivered once and P is not repeated",
      _p2_exc is None and _off_emitted.count(("p reply", _P)) == 1
      and [t for t, p in _off_emitted if p is None] == [f"pb {i:03d}" for i in range(120)],
      f"exc={_p2_exc!r} replies={[e for e in _off_emitted if e[1]]} top={len(_off_emitted)}")

# 10y-xix. ONE BUDGET PER POLL BOUNDS EVERY SWEEP CALL - history pages AND replies
#      calls. 80 tracked threads with parents older than the window each cost a
#      replies call; with three calls a poll the sweep makes at most three per
#      poll, resumes after the last thread it finished, and reads each thread
#      exactly once. Two sweeps handed the same budget share it: together they
#      make no more calls than it holds.
_many = [_ago(10 * _DAY - i) for i in range(80)]
_fk = _FakeSlack(_CHATTER + [_msg(t, f"old parent {i}") for i, t in enumerate(_many)],
                 {t: [_msg(_ago(60 + i), f"r{i:02d}")] for i, t in enumerate(_many)})
_st_m = {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
         "threads": {t: _ago(3 * _DAY) for t in _many}}
_edge_m = _poll(_fk, "C_MANY", _st_m)
_pos_m = w.new_sweep(_edge_m) if hasattr(w, "new_sweep") else None
_off_emitted.clear()
_m_calls, _m_done, _m_exc = [], False, None
for _ in range(40):
    _n0 = len(_fk.calls)
    _m_done, _m_exc = _try_sweep(_fk, "C_MANY", _st_m, pos=_pos_m, budget={"left": 3})
    _m_calls.append(len(_fk.calls) - _n0)
    if _m_done or _m_exc:
        break
check("10y-xix. a three-call budget holds every poll's sweep to three calls, pages and replies alike",
      _m_exc is None and _m_done is True and max(_m_calls) <= 3 and sum(_m_calls) == 81,
      f"exc={_m_exc!r} done={_m_done} calls per poll={_m_calls}")
check("10y-xix. ...and the resumed sweep reads each of the 80 threads exactly once",
      all(_fk.n("conversations.replies", ts=t) == 1 for t in _many)
      and sorted(x for x, _p in _off_emitted) == [f"r{i:02d}" for i in range(80)],
      f"emitted={len(_off_emitted)}")
_fk = _FakeSlack(_CHATTER + [_msg(t, "p") for t in _many],
                 {t: [_msg(_ago(60), "r")] for t in _many})
_shared = {"left": 3}
_n0 = len(_fk.calls)
for _cid in ("C_SH1", "C_SH2"):
    _st_sh = {"channel_ts": _NEWEST, "baseline_ts": _ago(30 * _DAY), "sweep_floor_ts": _ago(_DAY),
              "threads": {t: _ago(3 * _DAY) for t in _many}}
    _try_sweep(_fk, _cid, _st_sh, _poll(_fk, _cid, _st_sh), budget=_shared)
_sh_sweep_calls = [m for m, p, _ in _fk.calls[_n0:] if m == "conversations.replies"
                   or (m == "conversations.history" and "latest" in p)]
check("10y-xix. two sweeps handed one budget make no more calls together than it holds",
      len(_sh_sweep_calls) == 3 and _shared["left"] == 0,
      f"sweep calls={len(_sh_sweep_calls)} left={_shared}")

w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _emitted.append(
    (channel_name, msg["text"]))   # restore the section's emit stub

# === 11. CONFIG (config.json): nothing workspace-specific is hardcoded ==========
# Every case runs the REAL script in a subprocess with SLACK_WATCH_CONFIG pointed
# at a fixture, so it exercises the actual startup path. Still offline: all of
# these resolve (or die) at import, before any API call.

import json as _json
import subprocess
import tempfile

# The example config, the one forced at the top of this file: every case below
# derives its expectations from it rather than from an install's values.
_BASE_CFG = _json.loads(open(os.environ["SLACK_WATCH_CONFIG"]).read())


def _run_with_cfg(cfg_obj, snippet="", env_extra=None):
    """Run the real watch.py under a fixture config; return (rc, stdout, stderr).

    `snippet` is python executed AFTER importing the module as `m`, so a case can
    read resolved values. With no snippet the module is merely imported, which is
    what the fatal-config cases need.
    """
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cfg.json")
        if cfg_obj is not None:
            with open(p, "w") as f:
                _json.dump(cfg_obj, f)
        env = {**os.environ, "SLACK_WATCH_CONFIG": p}
        env.pop("SLACK_WATCH_POLL_SECS", None)
        env.pop("SLACK_WATCH_SWEEP_SECS", None)
        env.pop("SLACK_WATCH_SWEEP_BUDGET", None)
        env.update(env_extra or {})
        code = (
            "import importlib.util,sys\n"
            f"s=importlib.util.spec_from_file_location('m',{_SCRIPT!r})\n"
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n" + snippet
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()


# 11a. Every value the module resolves comes from the config file and nowhere
#      else. The prefix has to drive BOTH the cursor filename and the lock
#      filename, and known_users has to arrive with its _comment key stripped.
#      ⚠️ The expectation is DERIVED from the config, never transcribed from it.
#      A case pinning one workspace's literals, a known-user COUNT included, reds
#      whenever a new person is labelled, and no other workspace's config can
#      ever pass it. A test that pins a tally is a test that fails on data, not on
#      behaviour.
_cfg_users = sorted(k for k in _BASE_CFG["known_users"] if not k.startswith("_"))
_expected = " ".join([
    _BASE_CFG["bot"]["user_id"],
    _BASE_CFG["workspace"]["team_id"],
    _BASE_CFG.get("slack", {}).get("api_base", "https://slack.com/api"),
    f'{_BASE_CFG["state"]["prefix"]}-C1.json',
    f'{_BASE_CFG["state"]["prefix"]}.lock',
    _cfg_users[0],
    str(len(_cfg_users)),
])
_rc, _out, _err = _run_with_cfg(
    _BASE_CFG,
    "print(m.BOT_USER, m.TEAM_ID, m.API_BASE, m.state_file('C1').split('/')[-1], "
    "m.LOCK_FILE.split('/')[-1], sorted(m.KNOWN_USERS)[0], len(m.KNOWN_USERS))",
)
check("every module value resolves from the config file, and _comment is stripped",
      _out == _expected,
      f"rc={_rc} out={_out!r} want={_expected!r} err={_err!r}")

# 11b. TEETH - a missing REQUIRED key is fatal and NAMES itself. A watcher that
#      silently defaulted an identity value would poll the wrong workspace.
_missing = _json.loads(_json.dumps(_BASE_CFG))
del _missing["bot"]["user_id"]
_rc, _out, _err = _run_with_cfg(_missing)
check("missing required key exits non-zero naming the key",
      _rc != 0 and "bot.user_id" in _err, f"rc={_rc} err={_err!r}")

# 11c. A missing config FILE is fatal too (not an empty-config fallback).
_rc, _out, _err = _run_with_cfg(None)
check("missing config file exits non-zero", _rc != 0 and "missing config file" in _err,
      f"rc={_rc} err={_err!r}")

# 11c-ii. An UNSET SLACK_WATCH_CONFIG is fatal and says so. The variable is the
#      watcher contract's only configuration channel, and the skill directory
#      holds no config to fall back on: a default path would read whatever file
#      happened to sit there, or report a missing file nobody was meant to create.
_unset_env = {k: v for k, v in os.environ.items() if k != "SLACK_WATCH_CONFIG"}
_unset = subprocess.run(
    [sys.executable, "-c",
     "import importlib.util\n"
     f"s=importlib.util.spec_from_file_location('m',{_SCRIPT!r})\n"
     "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"],
    capture_output=True, text=True, env=_unset_env, cwd=os.path.dirname(_SCRIPT))
check("an unset SLACK_WATCH_CONFIG exits non-zero naming the variable",
      _unset.returncode != 0 and "WATCH-CONFIG SLACK_WATCH_CONFIG is not set" in _unset.stderr,
      f"rc={_unset.returncode} err={_unset.stderr.strip()!r}")

# 11d. Optional keys DO default - the poll tunables are the only such family, and
#      dropping them must not be fatal (contrast with 11b, which is what gives
#      "required" its meaning).
_nopoll = _json.loads(_json.dumps(_BASE_CFG))
del _nopoll["poll"]
_rc, _out, _err = _run_with_cfg(_nopoll, "print(m.POLL_SECS, m.DM_BASELINE_WINDOW_SECS)")
check("optional poll tunables fall back to defaults", _rc == 0 and _out == "5.0 90.0",
      f"rc={_rc} out={_out!r} err={_err!r}")

# 11e. Env still OUTRANKS config for the tunables (the live Monitor is armed with
#      SLACK_WATCH_POLL_SECS=30; a config that silently won would slow it to 5s).
_rc, _out, _err = _run_with_cfg(_BASE_CFG, "print(m.POLL_SECS)",
                                env_extra={"SLACK_WATCH_POLL_SECS": "30"})
check("env var outranks the config value for poll_secs", _rc == 0 and _out == "30.0",
      f"rc={_rc} out={_out!r} err={_err!r}")

# 11f. Retargeting to another workspace is a CONFIG edit only - no code change.
#      This is the whole point of the file, so assert it end-to-end.
_other = _json.loads(_json.dumps(_BASE_CFG))
_other["workspace"] = {"domain": "other.slack.com", "team_id": "T999OTHER"}
_other["bot"]["user_id"] = "U999BOT"
_other["state"]["prefix"] = "other-watch"
_other["owner"]["claude_config_dir"] = "~/.claude-other"
_other["known_users"] = {"U999HUMAN": "Someone"}
_rc, _out, _err = _run_with_cfg(
    _other,
    "print(m.TEAM_ID, m.BOT_USER, m.OWNER_CONFIG_DIR, m.state_file('C1').split('/')[-1], "
    "m.LOCK_FILE.split('/')[-1], m.KNOWN_USERS)",
)
check("a second workspace needs only a new config (ids, owner, state prefix all move)",
      _rc == 0 and _out == "T999OTHER U999BOT ~/.claude-other other-watch-C1.json "
                           "other-watch.lock {'U999HUMAN': 'Someone'}",
      f"rc={_rc} out={_out!r} err={_err!r}")

# 11g. config.json documents itself with _comment keys (JSON has no comments).
#      They must never be read as data - a "_comment" label under known_users
#      would surface as a member of the workspace.
check("_comment keys are stripped from known_users", "_comment" not in w.KNOWN_USERS,
      f"known_users keys={sorted(w.KNOWN_USERS)}")

# 11h. The workspace field is ENFORCED, not decorative: config and token can
#      disagree (nothing keeps them in step), and unchecked that is silent -
#      strangers posting under the other workspace's familiar names.
_authed = {"team_id": None}
w.api = lambda method, **p: {"team_id": _authed["team_id"]}
# The check first requires a readable token file (17m); api is stubbed here, so any
# readable file stands in for it.
_real_token_11h, w.TOKEN_FILE = w.TOKEN_FILE, os.path.realpath(__file__)
_authed["team_id"] = w.TEAM_ID
try:
    w.assert_configured_workspace()
    check("matching team_id passes the workspace check", True)
except SystemExit as e:
    check("matching team_id passes the workspace check", False, f"exited: {e}")
_authed["team_id"] = "T0WRONG"
try:
    w.assert_configured_workspace()
    check("token from a FOREIGN workspace is refused", False, "did not exit")
except SystemExit as e:
    check("token from a FOREIGN workspace is refused",
          "mismatch" in str(e) and "T0WRONG" in str(e), f"exit msg={e}")
w.TOKEN_FILE = _real_token_11h

# === 12. TOKEN PATH EXPANSION ==================================================
# The key file lives outside every checkout, so `token.path` has to be able to
# name a location that is not repo-relative and not machine-specific. Three
# forms have to expand, and NOTHING in the JSON layer expands any of them: json
# is a data format, os.path.expandvars does not know `:-` or `~`, and
# os.path.expanduser does not know variables. So the expansion is watch.py's
# own, and these are the cases that say it works.
#
# The last case is the NEGATIVE CONTROL and it is the load-bearing one. Delete
# it and the rest still pass while an unset variable could be silently swallowed
# into an empty string - which resolves to a DIFFERENT, existing file
# ("/tok" style) instead of failing. If it ever goes green in the wrong
# direction, the expansion has started guessing and no other case can see it.
_HOME = os.path.expanduser("~")


def _token_for(value, env_extra=None):
    c = _json.loads(_json.dumps(_BASE_CFG))
    c["token"]["path"] = value
    rc, out, err = _run_with_cfg(c, "print(m.TOKEN_FILE)", env_extra=env_extra)
    return rc, out, err


_rc, _out, _err = _token_for("${SKILL_TEST_STORE:-$HOME/.fallback-store}/tok")
check("${VAR:-default} falls back when VAR is unset",
      _rc == 0 and _out == f"{_HOME}/.fallback-store/tok", f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _token_for("${SKILL_TEST_STORE:-$HOME/.fallback-store}/tok",
                             env_extra={"SKILL_TEST_STORE": "/srv/store"})
check("${VAR:-default} takes VAR when it is set",
      _rc == 0 and _out == "/srv/store/tok", f"rc={_rc} out={_out!r} err={_err!r}")

# Shell `:-` semantics: an EMPTY variable is unset. A caller that exported the
# variable to "" gets the default, not a path rooted at "/".
_rc, _out, _err = _token_for("${SKILL_TEST_STORE:-$HOME/.fallback-store}/tok",
                             env_extra={"SKILL_TEST_STORE": ""})
check("an EMPTY VAR takes the default too (shell :- semantics)",
      _rc == 0 and _out == f"{_HOME}/.fallback-store/tok", f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _token_for("~/.some-store/tok")
check("a leading ~ expands to this user's home",
      _rc == 0 and _out == f"{_HOME}/.some-store/tok", f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _token_for("/absolute/store/tok")
check("an absolute path is used as given",
      _rc == 0 and _out == "/absolute/store/tok", f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _token_for("$SKILL_TEST_NEVER_SET/tok")
check("NEGATIVE CONTROL: an unset $VAR with no default stays literal, naming itself",
      _rc == 0 and _out == "$SKILL_TEST_NEVER_SET/tok",
      f"rc={_rc} out={_out!r} err={_err!r}")

# === 13. STATE DIR EXPANSION ===================================================
# `state.dir` decides where every cursor file and the single-instance lock live,
# and it is resolved by the same expand_path as `token.path` - deliberately, and
# this section is why. The two keys sit in one config file and only one of them
# advertises ${VAR:-default} in its comment, so that is the form an author will
# reach for in BOTH. Under a bare expanduser the ${...} form stays LITERAL, which
# makes the path RELATIVE, which puts the cursors and the lock in whatever
# directory the watcher happened to start in: every conversation re-baselines to
# "now" and a second watcher started elsewhere takes a DIFFERENT lock and
# double-emits. That is the identical failure watch.py's XDG_CACHE_HOME="" block
# exists to prevent, reached by another door - so if this section is ever deleted
# as redundant, the door reopens with nothing to notice it.


def _statedir_for(raw, env_extra=None):
    cfg = _json.loads(_json.dumps(_BASE_CFG))
    cfg["state"]["dir"] = raw
    return _run_with_cfg(cfg, "print(m.CACHE_DIR)", env_extra=env_extra)


_DEFAULTED_FORM = "${SKILL_TEST_STATE:-$HOME/.fallback-state}/watch"

# REGIME CONTROL, and it is the load-bearing half: assert the fixture really is
# a form expanduser CANNOT resolve. A fixture that drifted to a plain `~/...`
# would stay green under the very regression this section exists to catch, and
# nothing else in the suite would notice.
check("REGIME CONTROL: the fixture is a form expanduser leaves literal and RELATIVE",
      os.path.expanduser(_DEFAULTED_FORM) == _DEFAULTED_FORM
      and not os.path.isabs(os.path.expanduser(_DEFAULTED_FORM)),
      f"expanduser({_DEFAULTED_FORM!r}) = {os.path.expanduser(_DEFAULTED_FORM)!r}")

_rc, _out, _err = _statedir_for(_DEFAULTED_FORM)
check("state.dir expands ${VAR:-default} to an ABSOLUTE path, as token.path does",
      _rc == 0 and _out == f"{_HOME}/.fallback-state/watch" and os.path.isabs(_out),
      f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _statedir_for("~/.some-state/watch")
check("state.dir expands a leading ~",
      _rc == 0 and _out == f"{_HOME}/.some-state/watch",
      f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _statedir_for("/absolute/state/watch")
check("an absolute state.dir is used as given",
      _rc == 0 and _out == "/absolute/state/watch",
      f"rc={_rc} out={_out!r} err={_err!r}")

# No state.dir at all -> XDG, then ~/.cache. The fallback chain is what every
# pre-existing install runs on, so it is pinned rather than assumed.
_nodir = _json.loads(_json.dumps(_BASE_CFG))
del _nodir["state"]["dir"]
_rc, _out, _err = _run_with_cfg(_nodir, "print(m.CACHE_DIR)",
                                env_extra={"XDG_CACHE_HOME": "/xdg/cache"})
check("no state.dir falls back to XDG_CACHE_HOME",
      _rc == 0 and _out == "/xdg/cache", f"rc={_rc} out={_out!r} err={_err!r}")

_rc, _out, _err = _run_with_cfg(_nodir, "print(m.CACHE_DIR)",
                                env_extra={"XDG_CACHE_HOME": ""})
check("an EMPTY XDG_CACHE_HOME falls back to ~/.cache, never to a relative path",
      _rc == 0 and _out == f"{_HOME}/.cache" and os.path.isabs(_out),
      f"rc={_rc} out={_out!r} err={_err!r}")

# === 14. DELIVERY: every sender but this bot ===================================
# THE RULE THIS SECTION PINS. A message is delivered when it carries a `user`,
# that user is not this bot, and it has no `subtype`. Nothing else is consulted -
# in particular NOT `bot_id`, so a message from another bot is delivered exactly
# like a human's.
#
# ⚠️ WHY `bot_id` MUST NOT COME BACK INTO THE PREDICATE. Every post a fleet agent
# makes through `chat.postMessage` carries `bot_id` (with `user` = that agent's
# own user id and no subtype), so a `not msg.get("bot_id")` clause makes two
# fleet agents invisible to each other - direct `<@uid>` mentions in a shared
# channel included - and it fails silently: nothing errors, nothing is logged,
# and a message that was never delivered is indistinguishable from one that was
# never sent. "Filter out the bot noise" is how such a clause gets reintroduced,
# and 14a plus 14j are the only things in this file that would notice.
#
# ⚠️ WHAT STOPS A MACHINE FEED WAKING THE SESSION IS CHANNEL MEMBERSHIP, and it
# is not testable here. The watcher polls every conversation the bot belongs to,
# so a product bot's per-job feed lands message for message in any shared
# channel. `/invite` subscribes and `/kick` unsubscribes; there is no per-sender
# filter underneath. Do not "restore" one to fix a noisy channel - leave the
# channel.
#
# ⚠️ IF ANY CHECK IN THIS SECTION IS DELETED, THE RULE STOPS BEING THE RULE AND
# NOTHING ELSE IN THIS FILE NOTICES. The checks are each other's controls, in
# both directions, and are only meaningful as a set:
#   - 14a alone would pass under a predicate that delivers EVERYTHING.
#   - 14b/14c/14d are what refuse that: the self-echo guard, the subtype clause
#     and the no-UID clause are the only three things that may ever be dropped.
#   - 14b is the one with a runtime cost behind it: a watcher reading its own
#     posts back is a poll-rate feedback loop, not merely noise, and at this
#     watcher's rate limit it goes deaf.
#   - a predicate degenerated to `return False` reds 14a and the human case in
#     14e; degenerated to `return True` it reds 14b, 14c and 14d.

# The fixture below is a REAL payload shape, not an invented one, and that
# distinction is the whole section's foundation: if the real shape differed, the
# regime control and 14a would go green together while the live watcher stayed
# blind to other bots - the "instrument broken, reports GREEN" state this file is
# arranged to refuse. Recorded 2026-09-04 from live `conversations.history` on a
# shared channel, two fleet bots, keys verbatim and ids replaced by placeholders:
#
#   bot one  ts 1788477426.835059  user U0ALAN  bot_id B0ALAN  app_id A0ALAN  + bot_profile, NO subtype key
#   bot two  ts 1788452084.608959  user U0BOT2  bot_id B0BOT2  app_id A0BOT2  + bot_profile, NO subtype key
#
# Two properties of that recording are load-bearing and neither is obvious:
# `user` IS present and IS the bot's own user id (not absent, as a webhook post's
# would be), and `subtype` is ABSENT rather than null - so the predicate's
# `msg.get("subtype") is None` is what makes it pass, and a rewrite to
# `"subtype" not in msg` would be equivalent here and NOT equivalent for a
# message that carries an explicit null. The fixture omits the key for that
# reason; do not "normalise" it to `"subtype": None`.
#
# ⚠️ RE-RECORD THIS IF THE OUTBOUND POSTING RECIPE CHANGES. Measured: passing
# `username`, `icon_emoji` or `icon_url` to chat.postMessage makes Slack emit
# `subtype: "bot_message"` with NO `user` field, which is NOT deliverable under
# this predicate. The recipe in SKILL.md passes none of the three, and that is
# why this works; SKILL.md's posting section carries the warning.
_OTHER_BOT = "U0ALAN"         # Alan - a fellow fleet agent
_FEED_BOT = "U0FEED"          # a product feed - a bot that only emits
_BOT_TS = "1788477426.835059"


def _bot_msg(uid, text="a bot says hi", ts=_BOT_TS):
    """A fleet bot's post as `conversations.history` really returns it."""
    return {"ts": ts, "user": uid, "bot_id": "B0ALAN",
            "app_id": "A0ALAN",
            "bot_profile": {"id": "B0ALAN", "name": "Alan",
                            "user_id": uid, "app_id": "A0ALAN"},
            "text": text}


_bm = _bot_msg(_OTHER_BOT)

# 14-REGIME CONTROL. Asserts the fixture is in the regime this section is named
# for: `bot_id` is the ONLY property that a reintroduced bot filter could key on
# to drop it. If the fixture ever drifts (loses bot_id, gains a subtype, loses
# `user`, becomes this bot), 14a would go green against a watcher that still
# cannot see another bot at all, and this section would silently become
# decorative. Do not delete it as redundant with 14a - it is what makes 14a mean
# anything.
check("REGIME CONTROL: bot_id is the ONLY reason the other-bot fixture could be dropped",
      bool(_bm.get("bot_id")) and _bm.get("user") == _OTHER_BOT
      and "subtype" not in _bm and _bm.get("user") != w.BOT_USER,
      f"fixture={_bm}")

# 14-STRUCTURE CONTROL. There is no allowlist and no sender config of any kind:
# the module must expose no such name. A reintroduced list would make every
# other check in this section pass while delivery depended on a file again.
check("STRUCTURE CONTROL: the module exposes no sender allowlist",
      not any(hasattr(w, _n) for _n in ("PEERS", "ALLOWED_BOTS", "BOT_ALLOWLIST")),
      f"module names={[n for n in dir(w) if n.isupper()]}")

_saved_known = w.KNOWN_USERS

# 14a. ANOTHER BOT IS DELIVERED, with no configuration anywhere.
check("another bot's message IS deliverable (bot_id set, nothing configured)",
      w.is_deliverable(_bm) is True, f"msg={_bm}")
check("...and so is a bot that only emits - membership, not the predicate, is the control",
      w.is_deliverable(_bot_msg(_FEED_BOT)) is True, f"msg={_bot_msg(_FEED_BOT)}")

# 14b. SELF-ECHO GUARD. This bot's own message is never deliverable, and the
#      `bot_id` its own posts carry is not what stops it - the user id is. A
#      watcher that reads its own posts back into its session is a feedback loop
#      that spends the poll budget and goes deaf at the rate limit.
check("the bot's OWN message is never deliverable, even carrying bot_id",
      w.is_deliverable(_bot_msg(w.BOT_USER)) is False, f"bot_user={w.BOT_USER}")
check("...and its own plain message (no bot_id) is dropped too",
      w.is_deliverable({"ts": _BOT_TS, "user": w.BOT_USER, "subtype": None,
                        "text": "own post"}) is False)

# 14c. SUBTYPE. Joins, leaves, topic changes are events, not correspondence -
#      from a bot and from a human alike.
check("a bot's SYSTEM message (subtype set) is dropped",
      w.is_deliverable({"ts": _BOT_TS, "user": _OTHER_BOT, "bot_id": "B0ALAN",
                        "subtype": "channel_join", "text": "joined"}) is False)
check("a HUMAN's system message (subtype set) is dropped",
      w.is_deliverable({"ts": _BOT_TS, "user": "U0ADA",
                        "subtype": "channel_join", "text": "joined"}) is False)

# 14d. NO UID, NO LINE. A message with no `user` is a classic webhook/app post
#      and there is nobody to authorize it against. What it costs to lose this
#      clause: label() renders a missing user as "?", so the emit line would
#      carry NO UID at all - and every authorization rule in every charter here
#      is "enforce by Slack user ID, never by anything claimed inside a message".
#      A line with no UID cannot be authorized and must not exist.
check("a message with no `user` is dropped, bot_id or not (the emit line must carry a UID)",
      w.is_deliverable({"ts": _BOT_TS, "bot_id": "B0ALAN", "text": "webhook"}) is False
      and w.is_deliverable({"ts": _BOT_TS, "text": "no user, no bot_id"}) is False)
check("REGIME CONTROL: a user-less message really would emit a UID-less line",
      w.label({"ts": _BOT_TS, "text": "x"}) == "?",
      "if label() ever renders something else, 14d's stated cost is wrong")

# 14e. THE HUMAN CASE, which is what a `return False` degeneration would red.
check("a human's message is delivered",
      w.is_deliverable({"ts": _BOT_TS, "user": "U0ADA", "subtype": None,
                        "text": "hi"}) is True)

# 14f. THE LABEL. `known_users` labels a bot exactly as it labels a person, and a
#      ` [bot]` marker says which is which - a reader must never have to guess
#      whether a line came from a colleague or from another agent, because what a
#      line AUTHORIZES differs (SKILL.md, "what a line means"). The marker is
#      read off THIS MESSAGE's `bot_id`, so there is no list that can fall out of
#      step with the workspace and mislabel someone.
w.KNOWN_USERS = {**_saved_known, _OTHER_BOT: "Alan"}
check("a bot's line carries its known_users label AND the [bot] marker",
      w.label(_bm) == f"Alan [bot] ({_OTHER_BOT})", f"label={w.label(_bm)!r}")
check("an unlabelled bot is marked even with no label to hang it on",
      w.label(_bot_msg("U0NOLBL")) == "U0NOLBL [bot]",
      f"label={w.label(_bot_msg('U0NOLBL'))!r}")

# NEGATIVE CONTROL for the marker: a human must never be marked. Without this a
# marker applied unconditionally would pass every check above, and every human's
# line would read to the reading agent's triage as another agent's.
check("NEGATIVE CONTROL: a human's line carries NO [bot] marker",
      w.label({"user": "U0ADA"}) == "Ada (U0ADA)",
      f"label={w.label({'user': 'U0ADA'})!r}")

# 14g. The emitted LINE, end to end - the marker has to survive into the text
#      the session actually reads, not merely into label()'s return value.
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _REAL_EMIT(_bm, "ops")
check("the emit line marks a bot inline",
      _buf.getvalue().strip()
      == f"SLACK #ops message [ts {_BOT_TS}] Alan [bot] ({_OTHER_BOT}): a bot says hi",
      f"line={_buf.getvalue().strip()!r}")


# 14j. THE FOUR DELIVERY PATHS, driven end to end through a stubbed api().
# ⚠️ THIS IS NOT REDUNDANT WITH 14a, AND DELETING IT REOPENS THE BUG. Everything
# above tests is_deliverable() and label() as pure functions. The predicate has
# FOUR call sites - initial_baseline (channel first sight), dm_initial_baseline
# (DM first sight), and poll_channel's top-level and thread-reply loops - and
# MEASURED on this commit: each one can be individually narrowed back to
# humans-only (`and is_deliverable(m) and not m.get("bot_id")`) with the other
# 100+ checks still passing, because no fixture anywhere else in this file
# contains a bot message that carries a `user`. The thread-reply site is the
# likeliest one to be re-narrowed by a future edit - it is where "why am I seeing
# bot noise in threads" would get patched - and it is the one that carries
# another agent's ANSWER to something this agent said.
w.KNOWN_USERS = {**_saved_known, _OTHER_BOT: "Alan"}
_bot_emitted = []
w.emit = lambda msg, channel_name, parent_ts=None, is_dm=False: _bot_emitted.append(
    (msg["text"], parent_ts))

# 14j-1. initial_baseline: the invite race, with bots in the window.
_pj = "1788477400.000000"
_win = [
    {"ts": _pj, "user": w.BOT_USER, "subtype": "channel_join", "text": "joined"},
    _bot_msg(_OTHER_BOT, "a bot, after the join", ts="1788477410.000000"),
    {"ts": "1788477420.000000", "user": "U0ADA", "text": "a human"},
    {"ts": "1788477425.000000", "user": w.BOT_USER, "text": "my own post"},
]
_b, _e = w.initial_baseline(list(_win), now=1788477430.0)
check("initial_baseline replays another BOT's post-join message, not this bot's own",
      [m["text"] for m in _e] == ["a bot, after the join", "a human"],
      f"emitted={[m['text'] for m in _e]}")

# 14j-2. dm_initial_baseline: same, on the DM first-sight window.
_b2, _e2 = w.dm_initial_baseline(list(_win[1:]), "1788477405.000000")
check("dm_initial_baseline replays another BOT's message, not this bot's own",
      [m["text"] for m in _e2] == ["a bot, after the join", "a human"],
      f"emitted={[m['text'] for m in _e2]}")

# 14j-3. poll_channel, both loops: a bot top-level message AND a bot reply inside
# a thread, with this bot's own post alongside in both places.
_PARENT = "1788477500.000000"


def _bot_poll_api(method, **params):
    if method == "conversations.history" and "oldest" in params:
        return {"messages": [{"ts": _pj, "user": w.BOT_USER, "subtype": "channel_join",
                              "text": "joined"}]}
    if method == "conversations.history":
        return {"messages": [
            _bot_msg(_OTHER_BOT, "bot top-level", ts="1788477510.000000"),
            _bot_msg(w.BOT_USER, "own top-level", ts="1788477511.000000"),
            {"ts": _PARENT, "user": "U0ADA", "text": "human parent",
             "reply_count": 2, "latest_reply": "1788477530.000000"},
        ]}
    if method == "conversations.replies":
        return {"messages": [
            {"ts": _PARENT, "user": "U0ADA", "text": "human parent"},
            _bot_msg(_OTHER_BOT, "bot reply in thread", ts="1788477520.000000"),
            _bot_msg(w.BOT_USER, "own reply in thread", ts="1788477530.000000"),
        ]}
    raise AssertionError(f"unexpected api call {method} {params}")


w.api = _bot_poll_api
_st_bot = {}
w.poll_channel("C_BOT", "ops", _st_bot)          # first sight: baseline only
_bot_emitted.clear()
w.poll_channel("C_BOT", "ops", _st_bot)          # the normal poll
check("poll_channel TOP-LEVEL loop delivers another bot and drops this bot's own",
      ("bot top-level", None) in _bot_emitted
      and ("own top-level", None) not in _bot_emitted, f"emitted={_bot_emitted}")
check("poll_channel THREAD-REPLY loop delivers another bot's reply and drops this bot's own",
      ("bot reply in thread", _PARENT) in _bot_emitted
      and ("own reply in thread", _PARENT) not in _bot_emitted, f"emitted={_bot_emitted}")
check("this bot's two messages are the ONLY things dropped (the human still lands)",
      sorted(t for t, _ in _bot_emitted)
      == ["bot reply in thread", "bot top-level", "human parent"],
      f"emitted={_bot_emitted}")

w.KNOWN_USERS = _saved_known
# ⚠️ `w.emit` and `w.api` are left as STUBS here. Section 14 is the last
# in-process section; a future section 15 that expects the real ones must
# restore them (`_REAL_EMIT`, captured before the first stub) or it will
# silently measure nothing.

# 14h. NO SENDER KEY IN THE CONFIG SURFACE, proved through the real startup path.
#      A config carrying a stale allowlist key must START and IGNORE it, never
#      resurrect a filter: an operator upgrading from a config that had one gets
#      the new behaviour, not a half-applied old one, and the key is inert rather
#      than fatal so the upgrade needs no coordinated edit.
_stale = _json.loads(_json.dumps(_BASE_CFG))
_stale["peers"] = ["U0ALAN"]
_rc, _out, _err = _run_with_cfg(
    _stale,
    "print(m.is_deliverable("
    "{'ts':'1.0','user':'U0OTHER','bot_id':'B1','subtype':None,'text':'x'}), "
    "hasattr(m,'PEERS'))",
)
check("a config carrying a stale sender allowlist starts, ignores it, and delivers",
      _rc == 0 and _out == "True False", f"rc={_rc} out={_out!r} err={_err!r}")

# 14i. config.example.json is the file an adopter copies, so a sender-filter key
#      reappearing there would teach the wrong model to everyone who installs the
#      skill next - and it would do so without a single line of code changing.
_example = _json.loads(open(os.path.join(os.path.dirname(_SCRIPT),
                                         "config.example.json")).read())
check("config.example.json carries no sender-allowlist key",
      not any(k in _example for k in ("peers", "allowed_bots", "bot_allowlist")),
      f"keys={sorted(_example)}")

# 15. RETIRING A CONVERSATION SLACK SAYS IS GONE.
#     The bug: main()'s per-conversation guard exists so ONE bad conversation
#     cannot kill the whole watch - but a PERMANENT failure then reprints every
#     POLL_SECS forever. Observed: a DM that stays in `users.conversations`
#     discovery while `conversations.history` on it answers `channel_not_found`
#     for a bot token, ~720 WATCH-ERROR lines an hour at the default 5s poll,
#     each one a Monitor wake-up, until Monitor's rate limiter stops the monitor
#     outright - after which the watcher is alive, silent, and looks healthy.
#     ⚠️ These cases are the ONLY thing standing between that guard and the
#     opposite defect: retiring a conversation that was merely having a bad
#     minute, which is permanent silence on a LIVE conversation with one line of
#     notice. 15d is that direction and must never be "simplified" into 15c -
#     they look like the same test and measure opposite failures.
class _StopLoop(Exception):
    pass


class _Clock:
    """Bounds main()'s otherwise endless while-loop, offline.

    main() has exactly one exit (`--once`), and `--once` polls ONCE - which
    cannot measure "one line across N polls", the whole property at issue here.
    So the loop is bounded at its only sleep: sleep number N raises, unwinding
    main() after exactly N completed polls. `time()` is frozen rather than
    delegated so nothing in this section can depend on the wall clock.
    """

    def __init__(self, polls):
        self.limit = polls
        self.polls = 0

    def sleep(self, _secs):
        self.polls += 1
        if self.polls >= self.limit:
            raise _StopLoop

    def time(self):
        return 1784577770.0


_ABSENT = object()


def _drive_main(polls, channels, dms, fail=None, rediscover_every=None, sweeps=None,
                sweep_every=None, sweep_fail=None, saves=None, once=False,
                sweep_unfinished=None, sweep_pages=None, empty_states=None, sweep_greedy=None):
    """Run main()'s REAL loop `polls` times with stubbed I/O.

    `channels`/`dms` are a dict, or a callable taking the 0-based discovery-cycle
    index (so a conversation can vanish from discovery and come back, and so a
    discovery call can raise). `fail` maps a conversation id to an exception
    factory, called on every poll of it.

    The sweep is stubbed too: `sweeps`, when given, collects (conversation id,
    0-based poll index) per sweep reached; `sweep_fail` maps a conversation id
    to an exception factory raised by every sweep of it; `sweep_every` sets
    SWEEP_EVERY; `sweep_unfinished` maps a conversation id to how many of its
    sweeps report "not complete yet" before one completes; `sweep_pages`, when
    given, collects the page budget each sweep was handed; `saves`, when given,
    collects one conversation id per save_state call; `empty_states` names the
    conversations whose loaded state is empty (never polled successfully).
    `once=True` runs main() as `--once` (one iteration, no sleep), which is the
    smoke-test path. `sweep_greedy`, when given, makes every sweep take the
    whole budget it is handed and never finish, collecting (conversation id,
    poll index, calls it found left).

    Returns (stderr lines, {conversation id: times poll_channel was reached}).
    ⚠️ The second element is not diagnostics, it is the POSITIVE EVIDENCE that
    the subject was reached: a quiet stderr is equally consistent with "retired
    correctly" and "the loop never ran", and without a reached-count every check
    below would pass just as well against a harness that does nothing at all.
    """
    fail = fail or {}
    sweep_fail = sweep_fail or {}
    sweep_unfinished = dict(sweep_unfinished or {})
    polled: dict[str, int] = {}
    calls = {"chan": 0, "dm": 0}

    def _disc_chan(*_a, **_k):
        n = calls["chan"]
        calls["chan"] += 1          # before the call: a raising stub must advance too
        return dict(channels(n)) if callable(channels) else dict(channels)

    def _disc_dm(*_a, **_k):
        n = calls["dm"]
        calls["dm"] += 1
        return dict(dms(n)) if callable(dms) else dict(dms)

    def _poll(cid, _cname, _state, is_dm=False):
        polled[cid] = polled.get(cid, 0) + 1
        if cid in fail:
            raise fail[cid]()
        return "1.0"   # an edge: something is off this conversation's page

    def _sweep(cid, _cname, _state, pos, is_dm=False, budget=None):
        if sweeps is not None:
            sweeps.append((cid, w.time.polls))
        if sweep_pages is not None:
            sweep_pages.append((w.time.polls, budget))
        if sweep_greedy is not None:
            sweep_greedy.append((cid, w.time.polls, budget["left"] if budget else None))
            if budget:
                budget["left"] = 0
            return False
        if cid in sweep_fail:
            exc = sweep_fail[cid]()
            if exc is not None:      # a factory may decline, to fail only some sweeps
                raise exc
        left = sweep_unfinished.get(cid, 0)
        if left:
            sweep_unfinished[cid] = left - 1
            return False
        return True

    def _save(cid, _st):
        if saves is not None:
            saves.append(cid)

    names = ("discover_channels", "discover_dms", "poll_channel", "load_state",
             "save_state", "assert_configured_workspace", "acquire_singleton_lock",
             "time", "REDISCOVER_EVERY", "sweep_channel", "SWEEP_EVERY")
    # _ABSENT, not a bare getattr: a module without a sweep must still be
    # drivable, so that tree REDS the sweep checks instead of crashing the file.
    saved = {n: getattr(w, n, _ABSENT) for n in names}
    argv = sys.argv
    buf = io.StringIO()
    try:
        w.discover_channels = _disc_chan
        w.discover_dms = _disc_dm
        w.poll_channel = _poll
        w.load_state = lambda cid: ({} if cid in (empty_states or ()) else
                                    {"channel_ts": "1.0", "baseline_ts": "1.0", "threads": {}})
        w.save_state = _save
        w.sweep_channel = _sweep
        w.assert_configured_workspace = lambda: None
        w.acquire_singleton_lock = lambda: None
        w.time = _Clock(polls)
        if rediscover_every is not None:
            w.REDISCOVER_EVERY = rediscover_every
        if sweep_every is not None:
            w.SWEEP_EVERY = sweep_every
        # NOT --once unless asked: --once polls once, and most cases here need N
        # polls (see _Clock).
        sys.argv = ["watch.py", "--once"] if once else ["watch.py"]
        with contextlib.redirect_stderr(buf):
            try:
                w.main()
            except _StopLoop:
                pass
    finally:
        for n, v in saved.items():
            if v is _ABSENT:
                if hasattr(w, n):
                    delattr(w, n)
            else:
                setattr(w, n, v)
        sys.argv = argv
    return [ln for ln in buf.getvalue().splitlines() if ln.strip()], polled


def _src(fn):
    """The source text of `fn`. Raises rather than returning "" if it cannot be
    read: a structural check that silently sees an empty string passes every
    `in` test it is given and reports a green it never measured."""
    import inspect
    text = inspect.getsource(fn)
    if not text.strip():
        raise RuntimeError(f"_src({fn.__name__}) came back empty - cannot measure")
    return text


def _info(lines):
    return [ln for ln in lines if ln.startswith("WATCH-INFO")]


def _error(lines):
    return [ln for ln in lines if ln.startswith("WATCH-ERROR")]


# 15a. THE PREDICATE, on its own. It reads `SlackApiError.code` - the code as
#      Slack sent it - and compares it EXACTLY. A substring test would retire a
#      conversation on any code that merely CONTAINS one of these.
for _code in sorted(w.GONE_CONVERSATION_ERRORS):
    check(f"predicate recognises {_code}",
          w.gone_conversation_reason(w.SlackApiError("conversations.history", _code)) == _code)
check("predicate ignores a code that only CONTAINS a gone code (exact match, not substring)",
      w.gone_conversation_reason(
          w.SlackApiError("conversations.history", "channel_not_found_variant")) is None)
check("predicate ignores a non-Slack exception (urllib/socket faults are transient)",
      w.gone_conversation_reason(TimeoutError("timed out")) is None)
check("predicate ignores a plain RuntimeError carrying no Slack error code",
      w.gone_conversation_reason(RuntimeError("conversations.history: channel_not_found")) is None)

# 15a-ii. ⚠️ THE CODE COMES OFF THE EXCEPTION, NOT OUT OF ITS MESSAGE - and this
#      is the check that keeps it that way. Recovering the code with
#      `str(exc).rsplit(":", 1)[-1]` is correct only while the message is exactly
#      "<method>: <code>". Appending ONE detail to that message breaks such a
#      parse silently in BOTH directions (a real gone-code stops matching
#      and the flood returns; an unrelated tail starts matching and a LIVE
#      conversation is retired) with nothing going red. So: an error whose MESSAGE
#      ends in a gone code but whose `.code` is something else must NOT retire,
#      and one whose message is decorated but whose `.code` is right MUST.
_decoy = w.SlackApiError("conversations.history", "ratelimited")
_decoy.args = ("conversations.history: ratelimited (retry after 30s): channel_not_found",)
check("a message ending in a gone code does not retire when .code says otherwise",
      w.gone_conversation_reason(_decoy) is None, f"str={_decoy}")
_decorated = w.SlackApiError("conversations.history", "channel_not_found")
_decorated.args = (f"{_decorated} (team T0ABC, req 12:34)",)
check("a DECORATED message still retires, because .code is untouched",
      w.gone_conversation_reason(_decorated) == "channel_not_found", f"str={_decorated}")
check("SlackApiError keeps api()'s exact historical message, so WATCH-ERROR text is unchanged",
      str(w.SlackApiError("conversations.history", "ratelimited"))
      == "conversations.history: ratelimited")
check("SlackApiError is a RuntimeError, so every existing `except RuntimeError` still catches it",
      issubclass(w.SlackApiError, RuntimeError))

# 15b. STRUCTURE CONTROL. Retirement means silence for the rest of the process,
#      so the set must exclude everything that recovers by itself and everything a
#      human fixes - the operator only learns about those by SEEING them repeat.
#      A future edit that widens the set has to delete these checks to do it.
for _never in ("ratelimited", "service_unavailable", "internal_error", "fatal_error",
               "missing_scope", "token_revoked", "account_inactive", "invalid_auth",
               "request_timeout"):
    check(f"{_never} is NOT a retiring error (transient or install-scoped)",
          _never not in w.GONE_CONVERSATION_ERRORS)

# 15b-ii. ⚠️ THE TWO CODES THAT READ AS PERMANENT AND STILL MUST NOT BE MEMBERS,
#      because DISCOVERY ALREADY CLEARS THEM. This is the check most likely to be
#      "corrected" by someone who reads `not_in_channel` and `is_archived` as
#      obviously gone-shaped - they were both in this set's first draft. They are
#      out because `users.conversations` lists only conversations the bot BELONGS
#      to, and both discovery calls pass `exclude_archived=true`, so either
#      condition drops the conversation from the watched set at the next
#      rediscovery on its own. Retiring them buys only the lines in between
#      (60s/5s = 12 polls at the defaults - a normal transient, not a flood) and
#      risks the far worse direction: a transient one - a freshly /invite-d
#      channel whose membership reaches `users.conversations` before the read path
#      agrees - would retire a LIVE channel on its first ever poll, permanently,
#      since the bot IS a member so it never leaves discovery to be un-retired.
#      15e-ii measures that this cannot happen. Deleting either half leaves the
#      other measuring nothing.
for _self_healing in ("not_in_channel", "is_archived"):
    check(f"{_self_healing} is NOT a retiring error (the next rediscovery drops it anyway)",
          _self_healing not in w.GONE_CONVERSATION_ERRORS)
check("discovery is what clears those two: membership-scoped AND exclude_archived",
      "users.conversations" in _src(w.discover_channels)
      and 'exclude_archived": "true"' in _src(w.discover_channels)
      and 'exclude_archived": "true"' in _src(w.discover_dms),
      "the 15b-ii argument rests on discovery being membership-scoped and archive-excluding; "
      "if that changed, re-derive the set rather than deleting this check")

# 15c. THE BUG, on the DM branch: one dead DM, four polls, ONE line - and the
#      healthy DM beside it keeps being polled every single poll.
_dead_lines, _dead_polled = _drive_main(
    polls=4, channels={},
    dms={"D0DEAD": "USLACKBOT", "D111": "U0ADA"},
    fail={"D0DEAD": lambda: w.SlackApiError("conversations.history", "channel_not_found")},
)
check("dead DM: exactly ONE WATCH-INFO across 4 polls",
      len(_info(_dead_lines)) == 1, f"info={_info(_dead_lines)}")
check("dead DM: the line carries the conversation id and the reason",
      bool(_info(_dead_lines))
      and "D0DEAD" in _info(_dead_lines)[0]
      and "channel_not_found" in _info(_dead_lines)[0],
      f"line={_info(_dead_lines)[0] if _info(_dead_lines) else None}")
check("dead DM: ZERO WATCH-ERROR lines (a watcher that never retires it emits one per poll → 4)",
      _error(_dead_lines) == [], f"errors={_error(_dead_lines)}")
check("dead DM: polled exactly once, then never again (retired, not just quiet)",
      _dead_polled.get("D0DEAD") == 1, f"polled={_dead_polled}")
check("dead DM does not stop the OTHER DMs - the live one polled every poll",
      _dead_polled.get("D111") == 4, f"polled={_dead_polled}")

# 15d. ⚠️ THE OPPOSITE FAILURE, and the reason 15c cannot be trusted alone: a
#      TRANSIENT error must still print every poll. Repetition IS the signal that
#      a fault which can end has not ended; retiring here would drop a live
#      conversation for the rest of the process behind a single line.
_flaky_lines, _flaky_polled = _drive_main(
    polls=4, channels={}, dms={"D111": "U0ADA"},
    fail={"D111": lambda: w.SlackApiError("conversations.history", "ratelimited")},
)
check("transient Slack error: WATCH-ERROR on EVERY poll (4 of them)",
      len(_error(_flaky_lines)) == 4, f"errors={_error(_flaky_lines)}")
check("transient Slack error: never retired - no WATCH-INFO",
      _info(_flaky_lines) == [], f"info={_info(_flaky_lines)}")
check("transient Slack error: the conversation keeps being polled",
      _flaky_polled.get("D111") == 4, f"polled={_flaky_polled}")
_to_lines, _to_polled = _drive_main(
    polls=3, channels={}, dms={"D111": "U0ADA"},
    fail={"D111": lambda: TimeoutError("timed out")},
)
check("non-Slack exception (timeout): WATCH-ERROR every poll, never retired",
      len(_error(_to_lines)) == 3 and _info(_to_lines) == [] and _to_polled.get("D111") == 3,
      f"errors={len(_error(_to_lines))} info={_info(_to_lines)} polled={_to_polled}")

# 15e. THE CHANNEL BRANCH, same property, same code: a channel that discovery
#      keeps returning while `conversations.history` says it does not exist.
_ch_lines, _ch_polled = _drive_main(
    polls=4, channels={"C0FEED": "feed", "C1": "general"}, dms={},
    fail={"C0FEED": lambda: w.SlackApiError("conversations.history", "channel_not_found")},
)
check("dead channel: exactly ONE WATCH-INFO across 4 polls, zero WATCH-ERROR",
      len(_info(_ch_lines)) == 1 and _error(_ch_lines) == [],
      f"info={_info(_ch_lines)} errors={_error(_ch_lines)}")
check("dead channel: the line names the channel AND its id",
      bool(_info(_ch_lines)) and "#feed" in _info(_ch_lines)[0]
      and "C0FEED" in _info(_ch_lines)[0] and "channel_not_found" in _info(_ch_lines)[0],
      f"line={_info(_ch_lines)[0] if _info(_ch_lines) else None}")
check("dead channel: polled once then retired; the live channel keeps polling",
      _ch_polled.get("C0FEED") == 1 and _ch_polled.get("C1") == 4, f"polled={_ch_polled}")

# 15e-ii. ⚠️ THE INVITE RACE, and the reason 15e cannot be trusted alone. A
#      channel the bot really is in, answering `not_in_channel` on its very first
#      poll because `users.conversations` saw the fresh membership before the read
#      path did, must NOT be retired: it is LIVE, the operator just invited it,
#      and it can never be un-retired because a member never leaves discovery. So
#      it keeps WATCH-ERRORing and self-heals the moment the read path catches up.
#      This is the opposite-direction control for 15e and must never be
#      "simplified" into it - they look like the same test on the same branch and
#      measure opposite failures. `is_archived` is checked the same way.
for _code in ("not_in_channel", "is_archived"):
    _race_lines, _race_polled = _drive_main(
        polls=3, channels={"C0FEED": "feed"}, dms={},
        fail={"C0FEED": lambda c=_code: w.SlackApiError("conversations.history", c)},
    )
    check(f"{_code} on a channel still in discovery: NEVER retired, polled every poll",
          len(_error(_race_lines)) == 3 and _info(_race_lines) == []
          and _race_polled.get("C0FEED") == 3,
          f"errors={len(_error(_race_lines))} info={_info(_race_lines)} polled={_race_polled}")

# 15f. REDISCOVERY DOES NOT RE-ADD IT. Without this the ~60s cycle would put the
#      conversation back and the flood resumes at one line per rediscovery -
#      slower than the original bug and just as endless. rediscover_every=1 puts
#      a full discovery between every poll, which is the regime that would break.
_re_lines, _re_polled = _drive_main(
    polls=4, channels={}, dms={"D0DEAD": "USLACKBOT"},
    fail={"D0DEAD": lambda: w.SlackApiError("conversations.history", "channel_not_found")},
    rediscover_every=1,
)
check("a rediscovery that still returns the retired DM does NOT re-add it",
      len(_info(_re_lines)) == 1 and _re_polled.get("D0DEAD") == 1,
      f"info={_info(_re_lines)} polled={_re_polled}")

# 15g. LEAVING DISCOVERY AND COMING BACK IS the one thing that clears it - a
#      conversation that dropped out of the watched set entirely and returned is
#      a new conversation as far as this process knows, and earns one fresh probe.
def _flapping_dms(n):
    # cycle 1: gone from discovery (this is what clears the retirement)
    return {"D111": "U0ADA"} if n == 1 else {"D0DEAD": "USLACKBOT",
                                                   "D111": "U0ADA"}
_flap_lines, _flap_polled = _drive_main(
    polls=4, channels={}, dms=_flapping_dms,
    fail={"D0DEAD": lambda: w.SlackApiError("conversations.history", "channel_not_found")},
    rediscover_every=1,
)
check("gone-from-discovery then back: probed once more (exactly 2 probes, 2 lines)",
      _flap_polled.get("D0DEAD") == 2 and len(_info(_flap_lines)) == 2,
      f"info={_info(_flap_lines)} polled={_flap_polled}")

# 15h. A FAILING DISCOVERY MUST NOT UN-RETIRE ANYTHING. Discovery failure keeps
#      the last known set on purpose; pruning against this cycle's raw result
#      instead of the effective set would read that as "everything disappeared",
#      clear every retirement, and re-flood on the next poll.
def _chan_then_broken(n):
    if n >= 1:
        raise w.SlackApiError("users.conversations", "ratelimited")
    return {"C0FEED": "feed", "C1": "general"}
_brk_lines, _brk_polled = _drive_main(
    polls=4, channels=_chan_then_broken, dms={},
    fail={"C0FEED": lambda: w.SlackApiError("conversations.history", "channel_not_found")},
    rediscover_every=1,
)
check("a transient DISCOVERY failure does not un-retire (still one line, one probe)",
      len(_info(_brk_lines)) == 1 and _brk_polled.get("C0FEED") == 1,
      f"info={_info(_brk_lines)} polled={_brk_polled}")
check("...and the discovery failure itself still WATCH-ERRORs every cycle",
      len([ln for ln in _error(_brk_lines) if "discovery" in ln]) == 3,
      f"errors={_error(_brk_lines)}")

# === 16. api() RETRIES A CUT READ INSTEAD OF LOSING THE POLL ===================
# THE BUG THIS SECTION PINS. A large `conversations.history` body (a DM full of
# image messages, ~264 KB) can be cut mid-body by the far side closing the
# connection cleanly. `resp.read()` then raises
# `http.client.IncompleteRead(66316 bytes read, 197309 more expected)` - the cut
# lands at the client's ~64 KiB TCP receive window, so it is a property of the
# LINK, not of the body, and it recurs at the same offset across unrelated
# response sizes. Recorded live on a DM (D0BIG), twice in a freshly
# started process, while a direct fetch of the same URL from another process
# returned the whole 263,621-byte body in ~1.3 s.
#
# ⚠️ WHY THIS IS A FAKE RESPONSE AND NOT A LIVE CALL. The fault is a link-level
# event that cannot be provoked from a healthy link - 16 live large-body calls
# during the investigation all returned whole. A live test of this path would be
# green on every machine and could never fail for the reason its name claims, so
# the only honest instrument is a response object that raises on command. That
# also keeps this file offline and token-free like every section above it.
#
# ⚠️ IF THIS SECTION IS DELETED, the retry can be "simplified" back out of
# `api()` with nothing anywhere going red: the watcher would still work on a
# healthy link, and the regression would only appear as WATCH-ERROR lines on a
# degraded one, months later, read as a network problem rather than a code one.
_ok_body = json.dumps({"ok": True, "messages": [{"ts": "1.0", "user": "U1"}]}).encode()
_err_body = json.dumps({"ok": False, "error": "ratelimited"}).encode()


class _FakeResp:
    """One HTTP response. `read()` raises whatever `outcome` says, once."""

    def __init__(self, outcome):
        self._outcome = outcome

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def _drive_api(outcomes, method="conversations.history"):
    """Run the REAL api() against a scripted sequence of response outcomes.

    Returns (result, exception, attempts, sleeps). Drives `_REAL_API`, NOT
    `w.api` - which sections above have long since replaced with their own
    fixture stubs. Patches only what api() reaches for (urlopen, the token
    path, the backoff sleep) and restores each, so no other section can
    inherit the stub.
    """
    calls = {"n": 0}
    sleeps = []

    def _fake_urlopen(req, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        # Exhausting the script is a HARNESS fault, not a subject failure: it
        # means api() issued more requests than this case scripted.
        if i >= len(outcomes):
            raise AssertionError(
                f"api() issued {i + 1} requests; only {len(outcomes)} scripted")
        return _FakeResp(outcomes[i])

    _real_urlopen, _real_token, _real_sleep = (
        urllib.request.urlopen, w.TOKEN_FILE, time.sleep)
    _tok = tempfile.NamedTemporaryFile("w", suffix=".token", delete=False)
    _tok.write("fixture-token-not-real\n")
    _tok.close()
    urllib.request.urlopen = _fake_urlopen
    w.TOKEN_FILE = _tok.name
    time.sleep = lambda s: sleeps.append(s)
    try:
        return _REAL_API(method), None, calls["n"], sleeps
    except BaseException as e:  # noqa: BLE001 - the case under test IS the raise
        return None, e, calls["n"], sleeps
    finally:
        urllib.request.urlopen = _real_urlopen
        w.TOKEN_FILE = _real_token
        time.sleep = _real_sleep
        os.unlink(_tok.name)


# 16-REGIME CONTROL. ⚠️ Asserts the harness actually reaches api()'s read path
# before any check below is allowed to mean anything. Without it, a typo'd
# patch target, a token file api() could not open, or a signature change would
# make every case below raise or short-circuit identically to the failures they
# claim to detect - i.e. the section would be measuring its own plumbing and
# reporting the comfortable answer. A clean body must parse, in EXACTLY one
# request, with no sleep.
_ctl_res, _ctl_exc, _ctl_n, _ctl_sleeps = _drive_api([_ok_body])
check("16-CONTROL: a whole body parses through the real api(), one request, no backoff",
      _ctl_exc is None and _ctl_res == json.loads(_ok_body)
      and _ctl_n == 1 and _ctl_sleeps == [],
      f"exc={_ctl_exc!r} n={_ctl_n} sleeps={_ctl_sleeps}")

# 16-CONSTANT CONTROL. ⚠️ 16b below asserts "attempts == w._READ_ATTEMPTS" so
# that raising the budget does not red it. That form is vacuously true if the
# budget is 1 - which is a watcher with NO retry, the exact regression this
# section exists to catch. Pin the budget as a retry budget, here, once.
# ⚠️ `getattr`, not `w._READ_ATTEMPTS`: on a watch.py with the retry removed the
# attribute is gone, and an AttributeError here would ABORT the section - the
# third outcome, "never actually ran", wearing the costume of a crash rather
# than reporting the failure each remaining check was written to report.
_BUDGET = getattr(w, "_READ_ATTEMPTS", None)
check("16-CONTROL: the read budget is a RETRY budget (>= 2 attempts)",
      isinstance(_BUDGET, int) and _BUDGET >= 2,
      f"_READ_ATTEMPTS={_BUDGET!r}")

# 16a. THE BUG. Two cut reads then a whole one: api() returns the parsed body.
#      On the unfixed code this raises the first IncompleteRead straight out of
#      api(), the caller's poll is lost, and main() prints one WATCH-ERROR.
_cut = lambda: http.client.IncompleteRead(b"x" * 66316, 197309)
_res, _exc, _n, _sl = _drive_api([_cut(), _cut(), _ok_body])
check("16a. two IncompleteReads then success: api() returns the body",
      _exc is None and _res == json.loads(_ok_body),
      f"exc={_exc!r} res={_res!r}")
check("16a. ...having issued exactly 3 requests, with a backoff between them",
      _n == 3 and len(_sl) == 2 and all(x > 0 for x in _sl) and _sl[1] > _sl[0],
      f"n={_n} sleeps={_sl}")

# 16a-ii. THE OTHER TWO RETRYABLE CLASSES, each on its own. A reset and a read
#         that outran the timeout are the same event seen differently by the
#         kernel; a retry set that covers only IncompleteRead would still lose
#         those polls, and 16a alone cannot see that.
for _name, _err in (("ConnectionResetError", ConnectionResetError(104, "reset")),
                    ("TimeoutError (socket.timeout)", TimeoutError("timed out"))):
    _r, _e, _nn, _ = _drive_api([_err, _ok_body])
    check(f"16a-ii. {_name} is retried too",
          _e is None and _r == json.loads(_ok_body) and _nn == 2,
          f"exc={_e!r} n={_nn}")

# 16b. TEETH - A PERSISTENT FAULT STILL REACHES THE OPERATOR. The retry must
#      give up and re-raise the ORIGINAL exception class, so main()'s
#      per-conversation WATCH-ERROR guard fires. A version
#      that swallowed the error (returned {} or an empty message list) would
#      leave the watcher ALIVE AND SILENT - a broken read indistinguishable
#      from a quiet conversation, which is the worst state this watcher has.
_res_b, _exc_b, _n_b, _ = _drive_api([_cut() for _ in range(_BUDGET or 1)])
check("16b. a persistent cut read still raises IncompleteRead (WATCH-ERROR fires)",
      isinstance(_exc_b, http.client.IncompleteRead) and _res_b is None,
      f"exc={_exc_b!r} res={_res_b!r}")
check("16b. ...after exactly the read budget, not forever",
      _n_b == _BUDGET, f"n={_n_b} budget={_BUDGET}")

# 16c. A SLACK-LEVEL ERROR IS AN ANSWER, NOT A FAILED READ, and must NOT be
#      retried. Re-issuing `ok:false` would triple the request rate on exactly
#      the condition where that is worst (`ratelimited`), and would triple the
#      probe counts section 15's retirement guard is built on. The whole
#      scripted sequence is ONE response, so a retry here raises the harness's
#      own AssertionError rather than passing quietly.
_res_c, _exc_c, _n_c, _ = _drive_api([_err_body])
check("16c. ok:false raises SlackApiError on the FIRST request, no retry",
      isinstance(_exc_c, w.SlackApiError) and _exc_c.code == "ratelimited" and _n_c == 1,
      f"exc={_exc_c!r} n={_n_c}")

# 16d. THE PARTIAL BODY IS NEVER USED. `IncompleteRead.partial` holds the bytes
#      that did arrive: at the measured cut that is 66,316 bytes of a 263,621
#      byte body, i.e. a message list with a quarter of the messages and no
#      closing brace. The tempting "salvage what arrived" version of this fix
#      would hand that to json.loads - and on the day it happened to parse it
#      would deliver a TRUNCATED history, advance the cursor past what it never
#      saw, and lose the rest permanently with nothing logged. That is strictly
#      worse than a WATCH-ERROR.
#      ⚠️ This case is measured with a partial that is VALID JSON on its own,
#      because a partial of invalid JSON (16a's) would raise on any salvage
#      attempt and so cannot tell a salvaging api() from a correct one.
_partial_ok = json.dumps({"ok": True, "messages": [{"ts": "0.1", "user": "PARTIAL"}]}).encode()
_res_d, _exc_d, _n_d, _ = _drive_api([http.client.IncompleteRead(_partial_ok, 197309),
                                      _ok_body])
check("16d. a cut read whose partial parses is still discarded and re-issued",
      _exc_d is None and _res_d == json.loads(_ok_body) and _n_d == 2,
      f"exc={_exc_d!r} res={_res_d!r} n={_n_d}")


# === 17. THE SWEEP IN main(): CADENCE, STAGGER, ISOLATION, CONFIG ================
# The sweep is what reads threads whose parent is off the poll's page, so a
# sweep that never runs leaves the watcher exactly as deaf as the one-page poll
# was - and nothing in the poll's own output would say so. These cases drive
# main()'s REAL loop (section 15's driver) with the sweep recorded, so each
# verdict carries positive evidence that the sweep was reached.
import re as _re
import urllib.error

_S_CHANS = {"C_S1": "one", "C_S2": "two", "C_S3": "three", "C_S4": "four"}
_S_DMS = {"D_S5": "U0GRACE"}

# 17a. CADENCE AND STAGGER. Every conversation is swept once per SWEEP_EVERY
#      polls - and not all on the same poll, because the sweep is the one burst
#      of extra history pages the watcher makes, and a burst that lands for
#      every conversation at once is the shape that meets the rate limit.
_sw = []
_lines, _polled = _drive_main(6, _S_CHANS, _S_DMS, sweeps=_sw, sweep_every=3)
_per = {cid: sum(1 for c, _p in _sw if c == cid) for cid in [*_S_CHANS, *_S_DMS]}
check("17a. POSITIVE EVIDENCE: the loop polled every conversation six times",
      _polled == {cid: 6 for cid in [*_S_CHANS, *_S_DMS]}, f"polled={_polled}")
check("17a. every conversation, DMs included, is swept once per SWEEP_EVERY polls",
      _per == {cid: 2 for cid in _per}, f"sweeps per conversation={_per} log={_sw}")
# The PHASE (poll index mod SWEEP_EVERY), not the poll index: without a
# stagger every conversation still sweeps on polls 0 and 3, which is two
# distinct polls and one phase - the burst this check exists to catch.
check("17a. the sweeps are staggered across phases, not all on one poll",
      len({p % 3 for _c, p in _sw}) > 1, f"sweep (conversation, poll)={sorted(_sw)}")

# 17b. `--once` (the smoke test) sweeps EVERY conversation, whatever its phase,
#      so a one-shot run exercises the sweep instead of skipping it by luck.
_sw = []
_lines, _polled = _drive_main(1, _S_CHANS, _S_DMS, sweeps=_sw, sweep_every=1000, once=True)
check("17b. --once sweeps every conversation exactly once",
      sorted(c for c, _p in _sw) == sorted([*_S_CHANS, *_S_DMS]), f"sweeps={_sw}")

# 17c. A SWEEP THAT FAILS IS ISOLATED. It costs one `WATCH-ERROR sweep ...` line
#      per failed sweep, never the conversation's poll, never a retirement - a
#      sweep error is not evidence the conversation is gone, because the poll of
#      that same conversation answered a moment earlier - and the state is saved
#      after it, so any cursor the sweep advanced before failing is kept.
_429 = lambda: urllib.error.HTTPError("https://slack.com/api/conversations.history", 429,
                                      "Too Many Requests", {}, None)
_gone = lambda: w.SlackApiError("conversations.history", "channel_not_found")
_sw, _saves = [], []
try:
    _lines, _polled = _drive_main(3, {"C_RL": "busy"}, {"D_GONE": "U0GRACE"}, sweeps=_sw,
                                  sweep_every=1, sweep_fail={"C_RL": _429, "D_GONE": _gone},
                                  saves=_saves)
    _escaped = None
except Exception as e:  # noqa: BLE001 - an escape IS the failure being measured
    _lines, _polled, _escaped = [], {}, e
check("17c. a sweep error never escapes main() (it would end the watcher)",
      _escaped is None, f"escaped={_escaped!r}")
_sweep_err = [ln for ln in _error(_lines) if ln.startswith("WATCH-ERROR sweep")]
check("17c. POSITIVE EVIDENCE: both conversations were swept on every poll",
      sorted(_sw) == sorted([(c, p) for c in ("C_RL", "D_GONE") for p in range(3)]),
      f"sweeps={_sw}")
check("17c. each failed sweep is ONE `WATCH-ERROR sweep` line naming the conversation",
      len(_sweep_err) == 6
      and sum("#busy" in ln for ln in _sweep_err) == 3
      and sum("DM D_GONE" in ln for ln in _sweep_err) == 3, f"lines={_lines}")
check("17c. a failed sweep never retires the conversation and never stops its poll",
      not _info(_lines) and _polled == {"C_RL": 3, "D_GONE": 3},
      f"info={_info(_lines)} polled={_polled}")
check("17c. the state is saved after every sweep, failed or not (one save per poll + one per sweep)",
      len(_saves) == 12, f"saves={len(_saves)}")

# 17d. THE FOLLOWER STILL DROPS A 429, and still passes every other sweep error.
#      The follower's filter is the default in transport.json (`watch.follow_include`),
#      read from there rather than copied here: a copy would keep passing after the
#      real filter changed.
_inc_err = "not a non-empty string"
try:
    with open(os.path.join(os.path.dirname(_SCRIPT), "transport.json")) as _tf:
        _inc = _json.load(_tf)["watch"]["follow_include"]
except (OSError, ValueError, KeyError, TypeError) as _te:
    _inc = None
    _inc_err = f"{type(_te).__name__}: {_te}"
if not isinstance(_inc, str) or not _inc:
    check("17d. the follower's default filter is readable from transport.json", False,
          f"watch.follow_include unreadable ({_inc_err}: {_inc!r}) - "
          f"cannot measure, NO VERDICT on 17d")
else:
    _flt = _re.compile(_inc)
    _l429 = [ln for ln in _sweep_err if "429" in ln]
    _lgone = [ln for ln in _sweep_err if "channel_not_found" in ln]
    check("17d. a 429 sweep line is dropped by the follower, like a per-conversation 429",
          _l429 and not any(_flt.search(ln) for ln in _l429), f"429 lines={_l429}")
    check("17d. a non-429 sweep error still reaches the session",
          _lgone and all(_flt.search(ln) for ln in _lgone), f"lines={_lgone}")

# 17e. A FAILED POLL SKIPS THAT CONVERSATION'S SWEEP for the cycle: the sweep
#      reads from the edge the poll's page reached, and a poll that raised
#      reached nothing.
_sw = []
_lines, _polled = _drive_main(2, {"C_OK": "ok", "C_BAD": "bad"}, {}, sweeps=_sw,
                              sweep_every=1, fail={"C_BAD": lambda: TimeoutError("timed out")})
check("17e. a conversation whose poll failed is not swept in that cycle; the others are",
      _polled == {"C_OK": 2, "C_BAD": 2} and sorted(_sw) == [("C_OK", 0), ("C_OK", 1)],
      f"polled={_polled} sweeps={_sw}")

# 17f. THE CADENCE IS ONE CONFIG VALUE: `poll.sweep_secs`, default 300, with
#      SLACK_WATCH_SWEEP_SECS outranking it like every other poll tunable, and
#      SWEEP_EVERY derived from it and the poll interval.
#      The fixture value differs from the default, so "read from the config" and
#      "fell back to the default" cannot both pass this check.
_swcfg = _json.loads(_json.dumps(_BASE_CFG))
_swcfg.setdefault("poll", {}).update(poll_secs=5, sweep_secs=150)
_rc, _out, _err = _run_with_cfg(_swcfg, "print(m.SWEEP_SECS, m.SWEEP_EVERY)")
check("17f. poll.sweep_secs is read from the config and SWEEP_EVERY derived from it",
      _rc == 0 and _out == "150.0 30", f"rc={_rc} out={_out!r} err={_err[-300:]!r}")
_rc, _out, _err = _run_with_cfg(_swcfg, "print(m.SWEEP_SECS)",
                                env_extra={"SLACK_WATCH_SWEEP_SECS": "120"})
check("17f. SLACK_WATCH_SWEEP_SECS outranks the config", _rc == 0 and _out == "120.0",
      f"rc={_rc} out={_out!r} err={_err[-300:]!r}")
_rc, _out, _err = _run_with_cfg(_nopoll, "print(m.SWEEP_SECS, m.SWEEP_EVERY)")
check("17f. with no poll block the sweep defaults to 300 s (60 polls at the 5 s default)",
      _rc == 0 and _out == "300.0 60", f"rc={_rc} out={_out!r} err={_err[-300:]!r}")

# 17g. THE WINDOW HAS ONE SPELLING. Seven days is a rule the poll's cap, the
#      sweep's history read and the tracked-thread test all apply; a second
#      spelling of it is a second rule waiting to disagree with the first.
_wsrc = open(_SCRIPT).read()
_spellings = _re.findall(r"604800|7\s*\*\s*24\s*\*\s*3600|7\s*\*\s*86400|7\s*\*\s*24\s*\*\s*60\s*\*\s*60",
                         _wsrc)
check("17g. the 7-day window is written exactly once, as WINDOW_SECS",
      getattr(w, "WINDOW_SECS", None) == 7 * 86400 and len(_spellings) == 1,
      f"WINDOW_SECS={getattr(w, 'WINDOW_SECS', None)} spellings={_spellings}")


# 17h. A SWEEP IN PROGRESS CONTINUES ON THE NEXT POLL, due or not, and the next
#      sweep starts only at a due poll after it completes. In the loop every
#      sweep of one poll is handed the SAME budget, fresh each poll at
#      SWEEP_BUDGET calls - one budget for all conversations, so sweeps in
#      progress together cannot stack; under --once none, so the smoke test
#      sweeps to completion.
import zlib as _zlib
_rc_id = "C_RES"
_p0 = (-_zlib.crc32(_rc_id.encode())) % 4      # the first poll this id is due at, SWEEP_EVERY=4
_sw, _pg = [], []
_lines, _polled = _drive_main(_p0 + 6, {_rc_id: "res"}, {}, sweeps=_sw, sweep_every=4,
                              sweep_unfinished={_rc_id: 2}, sweep_pages=_pg)
check("17h. an unfinished sweep continues on the following polls; the next starts at its due poll",
      [p for _c, p in _sw] == [_p0, _p0 + 1, _p0 + 2, _p0 + 4],
      f"first due poll={_p0} sweep polls={[p for _c, p in _sw]}")
_pg = []
_drive_main(3, {"C_B1": "one", "C_B2": "two"}, {"D_B3": "U0GRACE"}, sweeps=[], sweep_every=1,
            sweep_pages=_pg)
_by_poll = {}
for _poll_i, _b in _pg:
    _by_poll.setdefault(_poll_i, []).append(_b)
_want_left = getattr(w, "SWEEP_BUDGET", "<no SWEEP_BUDGET>")
check("17h. every sweep of one poll shares ONE budget, fresh each poll at SWEEP_BUDGET calls",
      sorted(_by_poll) == [0, 1, 2]
      and all(len(v) == 3 and all(b is v[0] for b in v) and isinstance(v[0], dict)
              and v[0].get("left") == _want_left for v in _by_poll.values())
      and len({id(v[0]) for v in _by_poll.values()}) == 3,
      f"budgets by poll={_by_poll}")
_pg = []
_drive_main(1, {_rc_id: "res"}, {}, sweeps=[], sweep_every=1000, once=True, sweep_pages=_pg)
check("17h. --once hands the sweep no budget, so it runs to completion",
      [b for _i, b in _pg] == [None], f"budgets={_pg}")

# 17h-b. A FAILED SWEEP RESUMES ON THE NEXT POLL ONLY AFTER A RATE LIMIT. A
#      rate limit clears by itself and its line is filtered, so the position is
#      kept; any other failure drops it and waits for the next due poll -
#      resuming every poll after a fault that does not clear would be a non-429
#      line every poll, the flood that stops the follower's Monitor.
def _fail_first(make):
    n = {"k": 0}

    def factory():
        n["k"] += 1
        return make() if n["k"] == 1 else None
    return factory


for _label, _make, _want in (
        ("a rate limit", lambda: urllib.error.HTTPError(
            "https://slack.com/api/conversations.history", 429, "Too Many Requests", {}, None),
         [_p0, _p0 + 1, _p0 + 4]),
        ("any other failure", lambda: w.SlackApiError("conversations.history", "invalid_cursor"),
         [_p0, _p0 + 4])):
    _sw = []
    try:
        _drive_main(_p0 + 6, {_rc_id: "res"}, {}, sweeps=_sw, sweep_every=4,
                    sweep_fail={_rc_id: _fail_first(_make)})
        _hb_exc = None
    except Exception as e:  # noqa: BLE001 - an escape from main() is the failure being measured
        _hb_exc = e
    check(f"17h-b. after {_label} the sweep "
          + ("resumes on the next poll" if len(_want) == 3 else "waits for its next due poll"),
          _hb_exc is None and [p for _c, p in _sw] == _want,
          f"exc={_hb_exc!r} first due poll={_p0} sweep polls={[p for _c, p in _sw]}")

# 17h-c. A SWEEP IN PROGRESS IS FORGOTTEN WHEN ITS CONVERSATION LEAVES
#      DISCOVERY: when the conversation comes back it is a new conversation as
#      far as the process knows, and its next sweep starts at its next due poll.
_pr_id = next(f"C_PR{i}" for i in range(1000) if _zlib.crc32(f"C_PR{i}".encode()) % 7 == 0)
# The middle discovery is NOT empty: an empty one keeps the last known set
# (main() treats it as a failed discovery), which would never remove anything.
_sw = []
_lines, _polled = _drive_main(6, lambda n: {"C_OTHER": "other"} if n == 1 else {_pr_id: "pr"}, {},
                              sweeps=_sw, sweep_every=7, sweep_unfinished={_pr_id: 10 ** 6},
                              rediscover_every=2)
check("17h-c. POSITIVE EVIDENCE: the conversation left discovery for two polls and came back",
      _polled.get(_pr_id) == 4 and _polled.get("C_OTHER") == 2, f"polled={_polled}")
check("17h-c. a sweep in progress does not continue after its conversation left discovery and returned",
      [p for c, p in _sw if c == _pr_id] == [0, 1], f"sweep polls={[(c, p) for c, p in _sw]}")

# 17l. A SATURATED BUDGET STILL REACHES EVERY CONVERSATION. The budget is taken
#      first-come, so five conversations whose sweeps never finish and take the
#      whole budget whenever they get any are the worst case: in a fixed order
#      the first would take it every poll and the rest would never sweep. The
#      order rotates every poll, so within five polls every one gets calls.
_greedy = []
_drive_main(5, {"C_G1": "g1", "C_G2": "g2", "C_G3": "g3", "C_G4": "g4"}, {"D_G5": "U0GRACE"},
            sweep_every=1, sweep_greedy=_greedy)
check("17l. POSITIVE EVIDENCE: all five conversations reached the sweep on all five polls",
      len(_greedy) == 25, f"sweep calls={len(_greedy)}")
check("17l. with the budget saturated, every conversation's sweep gets calls within five polls",
      {c for c, _p, left in _greedy if left} == {"C_G1", "C_G2", "C_G3", "C_G4", "D_G5"},
      f"conversations that got calls={sorted({c for c, _p, left in _greedy if left})}")

# 17i. A POLL THAT RAISES STILL SAVES. The cursors move message by message, so
#      a failed poll's state records what it delivered; unsaved, a restart
#      before the next good poll would deliver all of it again. A state that is
#      still EMPTY - a first sight that failed before deciding anything - is
#      not saved, so a conversation never polled successfully leaves no file.
_saves = []
_lines, _polled = _drive_main(2, {"C_OK2": "ok", "C_BAD2": "bad", "C_NEW2": "new"}, {},
                              fail={"C_BAD2": lambda: TimeoutError("timed out"),
                                    "C_NEW2": lambda: TimeoutError("timed out")},
                              saves=_saves, sweep_every=1000, empty_states={"C_NEW2"})
check("17i. POSITIVE EVIDENCE: all three conversations were polled twice",
      _polled == {"C_OK2": 2, "C_BAD2": 2, "C_NEW2": 2}, f"polled={_polled}")
check("17i. a poll that raised still saved its state, once per poll",
      _saves.count("C_BAD2") == 2, f"saves={_saves}")
check("17i. a failed first sight leaves no cursor file",
      _saves.count("C_NEW2") == 0, f"saves={_saves}")

# 17j. A SIGTERM MID-POLL SAVES THE STATE AND THEN DIES BY THE SIGNAL. SIGTERM's
#      default action ends the process without running any `finally`, so the
#      cursors a poll in flight had advanced - its lines already printed - would
#      be lost and printed again after the restart. And the process must still
#      end BY the signal, never with exit 0: the service restarts a watcher that
#      died by a signal and treats exit 0 as a deliberate stop (the WATCH-GUARD
#      refusals), so an exit 0 would leave it down after an ad-hoc kill.
#      Measured on a REAL process with a REAL signal through the real entry point
#      `run()`: a poll that blocks, a SIGTERM while it does, then the exit status
#      and whether save_state ran.
#      ⚠️ NEGATIVE CONTROL first: the same run with the handler suppressed must die
#      by the signal WITHOUT saving - "saved" is the one thing that separates the
#      two runs. If the control saves, or the poll was never reached, the
#      instrument is not measuring the handler: NO VERDICT.
#      ⚠️ The poll's "started" marker is a DIRECTORY (os.makedirs, idempotent for
#      a watcher that polls again), never a file written through open(). The
#      parent signals the moment the marker EXISTS, and open(p, 'w').write(..)
#      makes the file exist at open() but writes it later, in the file object's
#      finalizer, whose flush runs pending signal handlers. A SIGTERM landing
#      there raises Terminated INSIDE a finalizer, where CPython prints
#      "Exception ignored while finalizing file" and drops it: the child sleeps
#      on, the parent's wait times out, and the check reds as (reached, rc,
#      saved) = (True, 'timeout', False) with the watcher behaving correctly.
#      The window is microseconds wide, so only a child descheduled inside it -
#      a loaded runner - hits it. Making a directory is one system call and
#      leaves no object to finalize: once the marker exists, nothing between it
#      and the blocking sleep can swallow the signal. Measured on CPython 3.14
#      with an LD_PRELOAD shim holding every write() to a path ending in
#      /started for 2 s: the file-marker form reds 3 of 3 with exactly that
#      message, this form passes 3 of 3.
import signal as _signal


def _sigterm_run(install_handler):
    with tempfile.TemporaryDirectory() as d:
        cfg_path = os.path.join(d, "cfg.json")
        with open(cfg_path, "w") as f:
            _json.dump(_BASE_CFG, f)
        started, saved = os.path.join(d, "started"), os.path.join(d, "saved")
        suppress = "" if install_handler else \
            "m.signal = types.SimpleNamespace(signal=lambda *a: None, SIGTERM=15)\n"
        code = (
            "import importlib.util, os, sys, time, types\n"
            f"s = importlib.util.spec_from_file_location('m', {_SCRIPT!r})\n"
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "m.assert_configured_workspace = lambda: None\n"
            "m.acquire_singleton_lock = lambda: None\n"
            "m.discover_channels = lambda *a, **k: {'C1': 'one'}\n"
            "m.discover_dms = lambda *a, **k: {}\n"
            "m.load_state = lambda cid: {'channel_ts': '1.0', 'baseline_ts': '1.0', "
            "'sweep_floor_ts': '1.0', 'threads': {}}\n"
            f"m.save_state = lambda cid, st: open({saved!r}, 'w').write('saved')\n"
            "def _blocking_poll(*a, **k):\n"
            f"    os.makedirs({started!r}, exist_ok=True)\n"
            "    time.sleep(60)\n"
            "m.poll_channel = _blocking_poll\n"
            + suppress +
            "sys.argv = ['watch.py']\n"
            "m.run()\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_WATCH_")}
        env["SLACK_WATCH_CONFIG"] = cfg_path
        proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 20
        while not os.path.exists(started) and proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        reached = os.path.exists(started)
        if reached:
            proc.send_signal(_signal.SIGTERM)
        try:
            rc = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = "timeout"
        return reached, rc, os.path.exists(saved), (proc.stderr.read() or "")[-300:]


_ctl = _sigterm_run(install_handler=False)
if not (_ctl[0] and _ctl[1] == -_signal.SIGTERM and not _ctl[2]):
    check("17j. a SIGTERM mid-poll saves the state, then the process dies by SIGTERM", False,
          f"NO VERDICT - the negative control did not die unsaved by the signal "
          f"(reached, rc, saved, stderr)={_ctl}")
else:
    _run = _sigterm_run(install_handler=True)
    check("17j. a SIGTERM mid-poll saves the state, then the process dies by SIGTERM",
          _run[0] and _run[1] == -_signal.SIGTERM and _run[2],
          f"(reached, rc, saved, stderr)={_run} control={_ctl}")

# 17j-b. The WATCH-GUARD refusal still EXITS 0 through the same entry point: it
#      is how a watcher that does not own the surface stops for good, and the
#      SIGTERM path must not have swallowed it.
with tempfile.TemporaryDirectory() as _gd:
    _gcfg = os.path.join(_gd, "cfg.json")
    with open(_gcfg, "w") as _f:
        _json.dump(_BASE_CFG, _f)
    _genv = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_WATCH_")}
    _genv.update(SLACK_WATCH_CONFIG=_gcfg, CLAUDE_CONFIG_DIR=os.path.join(_gd, "not-the-owner"))
    _g = subprocess.run([sys.executable, "-c",
                         "import importlib.util, sys\n"
                         f"s = importlib.util.spec_from_file_location('m', {_SCRIPT!r})\n"
                         "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                         "sys.argv = ['watch.py']\nm.run()\n"],
                        env=_genv, capture_output=True, text=True, timeout=30)
check("17j-b. a WATCH-GUARD refusal through run() still exits 0",
      _g.returncode == 0 and "WATCH-GUARD" in _g.stderr, f"rc={_g.returncode} stderr={_g.stderr[-200:]!r}")
check("17j-b. the script's own entry is run(), so a real start takes the SIGTERM path",
      open(_SCRIPT).read().rstrip().endswith('if __name__ == "__main__":\n    run()'),
      "the __main__ block must call run()")

# 17k. THE SWEEP BUDGET IS ONE CONFIG VALUE: `poll.sweep_budget`, default 3, with
#      SLACK_WATCH_SWEEP_BUDGET outranking it like every other poll tunable.
_bcfg = _json.loads(_json.dumps(_BASE_CFG))
_bcfg.setdefault("poll", {})["sweep_budget"] = 7
_rc, _out, _err = _run_with_cfg(_bcfg, "print(m.SWEEP_BUDGET)")
check("17k. poll.sweep_budget is read from the config", _rc == 0 and _out == "7",
      f"rc={_rc} out={_out!r} err={_err[-300:]!r}")
_rc, _out, _err = _run_with_cfg(_bcfg, "print(m.SWEEP_BUDGET)",
                                env_extra={"SLACK_WATCH_SWEEP_BUDGET": "5"})
check("17k. SLACK_WATCH_SWEEP_BUDGET outranks the config", _rc == 0 and _out == "5",
      f"rc={_rc} out={_out!r} err={_err[-300:]!r}")
_rc, _out, _err = _run_with_cfg(_nopoll, "print(m.SWEEP_BUDGET)")
check("17k. with no poll block the sweep budget defaults to 3", _rc == 0 and _out == "3",
      f"rc={_rc} out={_out!r} err={_err[-300:]!r}")

# 17m. A TOKEN FILE THAT CANNOT BE READ IS A CONFIG PROBLEM, NOT A CRASH. Both forms
#      (`--once`, and the daemon form a unit runs) must stop with ONE `WATCH-CONFIG`
#      line naming `token.path` and the path, before any Slack call, never with the
#      traceback the first api() call's open() raises. Under the unit a traceback is
#      a crash loop whose only line is `FileNotFoundError`; the example's own token
#      path holds `<agents-root>`/`<agent>`, which nothing substitutes, so this is the
#      first thing a literal copy of the example hits. The exit is the other
#      WATCH-CONFIG exits' (1, never 0 or 2): the unit keeps restarting it, so a token
#      written later is picked up with nothing else to do.
with tempfile.TemporaryDirectory() as _td:
    _tcfg = _json.loads(_json.dumps(_BASE_CFG))
    _tcfg["token"]["path"] = os.path.join(_td, "no-such-dir", "slack-bot.key")
    _tcfg["owner"]["claude_config_dir"] = os.path.join(_td, "owner")
    _tcfg["state"]["dir"] = os.path.join(_td, "state")
    with open(os.path.join(_td, "cfg.json"), "w") as _f:
        _json.dump(_tcfg, _f)
    _tenv = {**os.environ, "SLACK_WATCH_CONFIG": os.path.join(_td, "cfg.json"),
             "CLAUDE_CONFIG_DIR": os.path.join(_td, "owner")}
    for _argv in (["--once"], []):
        _form = "--once" if _argv else "the daemon form"
        _t = subprocess.run([sys.executable, _SCRIPT, *_argv], env=_tenv, capture_output=True,
                            text=True, timeout=30)
        _lines = _t.stderr.strip().splitlines()
        check(f"17m. {_form}: a missing token file exits with one WATCH-CONFIG line naming token.path and the path",
              len(_lines) == 1 and _lines[0].startswith("WATCH-CONFIG ") and "token.path" in _lines[0]
              and _tcfg["token"]["path"] in _lines[0] and _t.stdout == "",
              f"rc={_t.returncode} stderr={_t.stderr[-400:]!r}")
        check(f"17m. {_form}: ...with the other WATCH-CONFIG exits' status, so the unit retries it",
              _t.returncode == 1, f"rc={_t.returncode}")
    # Regime control: the daemon form above reached the token check, i.e. it passed
    # the owner guard and took the lock - so the line is not the guard's.
    check("17m. control: the daemon-form run held the owner's lock (it got past the guard)",
          os.path.exists(os.path.join(_td, "state", f"{_tcfg['state']['prefix']}.lock")),
          f"state dir={sorted(os.listdir(_td))}")
    # 17m-ii. THE OWNER GUARD AND THE LOCK ARE THE DAEMON FORM'S. `--once` is the
    #      smoke test that runs beside a live watcher, so it checks neither, and
    #      SKILL.md (Ownership) and INSTRUCTION ("After installing") say so. Under a
    #      config dir that is not the owner's, the daemon form refuses with
    #      WATCH-GUARD (exit 0) while `--once` goes on to the token check.
    _oenv = {**_tenv, "CLAUDE_CONFIG_DIR": os.path.join(_td, "not-the-owner")}
    _d = subprocess.run([sys.executable, _SCRIPT], env=_oenv, capture_output=True, text=True, timeout=30)
    _o = subprocess.run([sys.executable, _SCRIPT, "--once"], env=_oenv, capture_output=True, text=True,
                        timeout=30)
    check("17m-ii. a non-owner's daemon form exits 0 with WATCH-GUARD",
          _d.returncode == 0 and _d.stderr.startswith("WATCH-GUARD not the owning agent"),
          f"rc={_d.returncode} stderr={_d.stderr[-300:]!r}")
    check("17m-ii. a non-owner's --once is not guarded: it reaches the token check",
          _o.returncode == 1 and _o.stderr.startswith("WATCH-CONFIG ") and "WATCH-GUARD" not in _o.stderr,
          f"rc={_o.returncode} stderr={_o.stderr[-300:]!r}")


print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
