#!/usr/bin/env python3
"""slack_manifest.test.py - offline regression guard for slack_manifest.py and slack-scopes.json.

Hermetic: no network, no config, no install. It imports the script from its own
directory and runs it as a subprocess with the same interpreter. Prints one line
per check and ALL CHECKS PASSED, or names every failure and exits 1.

WHAT EACH SECTION IS FOR, AND WHAT IS LOST IF IT IS REMOVED

1. The scope table is internally true. Every row names a source URL of the form
   the table's header records, token types from Slack's vocabulary, a why; every
   tier row is a Bot scope and every excluded row is not; the tiers nest. The
   integrity check is itself run against a deliberately broken copy of the table
   first (1a), because a check that finds nothing in the real table proves
   nothing until it has been seen to find something in a bad one. If 1a's broken
   copy passes, the section issues NO VERDICT rather than a green.
   This section cannot re-verify a row against Slack - the test has no network on
   purpose - so the rows' TRUTH rests on the dated fetch the table's header
   records. What it guards is the table staying the shape the validator trusts.

2. Positive controls. Each tier's generated manifest validates with zero
   findings, and the documented limits are exact: a 35-character app name and an
   80-character bot display name are VALID. Without the boundary cases a rule
   written `>= 35` instead of `> 35` refuses legal names and every negative
   control still passes.

3. Negative controls. Each takes the valid standard-tier manifest, changes ONE
   thing, and requires EXACTLY ONE finding, carrying the rule id the control is
   named for. Exactly one, and that id, is what makes a control measure its own
   rule: a control asserting only "invalid" stays green after its rule is
   deleted whenever any other rule happens to fire on the same input - an
   over-long name that also broke the JSON shape would "pass" with the length
   rule gone. IF THE BASELINE IS ITSELF INVALID, NO CONTROL MEANS ANYTHING:
   the section prints NO VERDICT and the run fails before any control is read.
   3z is the census: every rule in RULES has a control, so a rule added without
   one reds the run instead of shipping untested.

4. The CLI's three outcomes are distinct. generate refuses with exit 2 and an
   EMPTY stdout (a refused manifest that still reached stdout would be pasted);
   validate says 0 / 1 / 2 for valid / invalid / unreadable; granted says 0 / 1
   for equal / different and 2 NO VERDICT for input with no authenticated
   auth.test response in it - a call that never reached Slack, or a token Slack
   refused - because either one read as "the token is missing every scope"
   sends the person to fix the app when the token file is what is wrong.
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPT = os.path.join(HERE, "slack_manifest.py")
spec = importlib.util.spec_from_file_location("slack_manifest", SCRIPT)
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

FAILS = []


def check(cond, label):
    print(("ok   - " if cond else "FAIL - ") + label)
    if not cond:
        FAILS.append(label)


def run(*args, stdin=""):
    p = subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True,
                       text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------- 1. table
with open(sm.SCOPES_FILE, encoding="utf-8") as f:
    ROWS = json.load(f)["scopes"]
TABLE = sm.load_table()
TOKEN_VOCAB = {"Bot", "User", "Legacy Bot"}
URL_BASE = "https://docs.slack.dev/reference/scopes/"


def table_problems(rows):
    """Every way a row list breaks the contract the validator relies on."""
    probs = []
    names = [r.get("scope") for r in rows]
    if len(names) != len(set(names)):
        probs.append("duplicate scope rows")
    for r in rows:
        s = r.get("scope", "?")
        tt = r.get("token_types") or []
        if r.get("source") != URL_BASE + s.replace(":", "."):
            probs.append(f"{s}: source is not {URL_BASE}<scope with : as .>")
        if not tt or not set(tt) <= TOKEN_VOCAB:
            probs.append(f"{s}: token_types outside {sorted(TOKEN_VOCAB)}")
        if r.get("tier") is not None and "Bot" not in tt:
            probs.append(f"{s}: a tier requests it but Slack grants it no Bot token")
        if r.get("tier") is None and "Bot" in tt:
            probs.append(f"{s}: excluded from every tier but grantable to a Bot token")
        why = r.get("why", "")
        if not why.strip() or not why.isascii() or "|" in why:
            probs.append(f"{s}: why is empty, not ASCII, or holds a | that breaks the tiers table")
    return probs


broken = copy.deepcopy(ROWS)
broken[0]["source"] = URL_BASE + "nowhere"
next(r for r in broken if r["tier"] == "full")["token_types"] = ["User"]
next(r for r in broken if r["tier"] is None)["token_types"] = ["Bot", "User"]
broken.append(dict(broken[1]))
caught = table_problems(broken)
if len(caught) < 4:
    print(f"NO VERDICT on section 1: the integrity check found {len(caught)} of 4 planted defects, "
          "so a clean result on the real table would mean nothing")
    FAILS.append("section 1 integrity check is blind")
else:
    check(True, "1a integrity check finds all 4 defects planted in a broken copy")
    real = table_problems(ROWS)
    check(not real, "1b real scope table has no integrity problem" + (f": {real}" if real else ""))

tiers = {t: set(sm.tier_scopes(TABLE, t)) for t in sm.TIERS}
check(tiers["minimal"] < tiers["standard"] < tiers["full"], "1c tiers nest strictly: minimal < standard < full")
for t, must in (("minimal", {"channels:read", "channels:history", "groups:read", "groups:history", "chat:write"}),
                ("standard", {"im:read", "im:history", "im:write", "reactions:write", "files:write", "files:read"}),
                ("full", {"channels:manage", "groups:write", "usergroups:write", "pins:write",
                          "bookmarks:write", "users:read", "users.profile:read"})):
    check(must <= tiers[t], f"1d tier {t} carries the abilities it promises: {sorted(must - tiers[t]) or 'all present'}")
check(any(s.startswith("admin.") and r["tier"] is None for s, r in TABLE.items()),
      "1e the admin.* user-token-only abilities are listed as excluded")
with tempfile.TemporaryDirectory() as td:
    bad_file = os.path.join(td, "scopes.json")
    with open(bad_file, "w", encoding="utf-8") as f:
        json.dump({"scopes": [{"scope": "chat:write", "token_types": ["Bot"], "tier": "minimal",
                               "source": URL_BASE + "chat.write"}]}, f)
    try:
        sm.load_table(bad_file)
        check(False, "1f load_table refuses a row with no why")
    except ValueError:
        check(True, "1f load_table refuses a row with no why")

# ---------------------------------------------------------------- 2. positive
for t in sm.TIERS:
    m = sm.build(t, "Ada", description="A long-running fleet agent.", table=TABLE)
    f = sm.validate(m, TABLE)
    check(not f, f"2a generated {t} manifest validates" + (f": {f}" if f else ""))
    check(set(m["oauth_config"]["scopes"]["bot"]) == tiers[t], f"2b generated {t} manifest requests exactly its tier")
BASE = sm.build("standard", "Ada", table=TABLE)
edge = copy.deepcopy(BASE)
edge["display_information"]["name"] = "n" * 35
edge["features"]["bot_user"]["display_name"] = "d" * 80
check(not sm.validate(edge, TABLE), "2c a 35-character name and an 80-character display name are valid")
mini = sm.build("minimal", "Ada", table=TABLE)
check(mini["features"]["app_home"]["messages_tab_enabled"] is False,
      "2d minimal keeps the Messages tab closed (it cannot read DMs)")

# ---------------------------------------------------------------- 3. negative


def mutated(fn):
    m = copy.deepcopy(BASE)
    fn(m)
    return m


CONTROLS = [
    ("invented scope channels:fly", "slack.scope-known",
     lambda m: m["oauth_config"]["scopes"]["bot"].append("channels:fly")),
    ("user-token-only scope in the bot list", "slack.scope-token-type",
     lambda m: m["oauth_config"]["scopes"]["bot"].append("admin.conversations:write")),
    ("display_information.name missing", "slack.name",
     lambda m: m["display_information"].pop("name")),
    ("display_information.name of 36 characters", "slack.name",
     lambda m: m["display_information"].update(name="n" * 36)),
    ("unknown top-level key", "slack.top-level-keys",
     lambda m: m.update(socket_mode_enabled=False)),
    ("bot display name of 81 characters", "slack.bot-user",
     lambda m: m["features"]["bot_user"].update(display_name="d" * 81)),
    ("unknown settings key", "slack.settings",
     lambda m: m["settings"].update(socket_mode=False)),
    ("token rotation turned on", "fleet.polling-profile",
     lambda m: m["settings"].update(token_rotation_enabled=True)),
    ("DM scopes removed but the Messages tab left open", "fleet.dm-reachable",
     lambda m: m["oauth_config"]["scopes"].update(
         bot=[s for s in m["oauth_config"]["scopes"]["bot"] if s not in ("im:read", "im:history")])),
    ("unknown display_information key", "slack.display-information",
     lambda m: m["display_information"].update(icon="x")),
    ("description of 141 characters", "slack.description",
     lambda m: m["display_information"].update(description="d" * 141)),
    ("long_description of 174 characters", "slack.long-description",
     lambda m: m["display_information"].update(long_description="l" * 174)),
    ("background_color that is not hex", "slack.background-color",
     lambda m: m["display_information"].update(background_color="blue")),
    ("unknown features key", "slack.features",
     lambda m: m["features"].update(workflow={})),
    ("app_home value that is not a boolean", "slack.app-home",
     lambda m: m["features"]["app_home"].update(home_tab_enabled="no")),
    ("unknown oauth_config key", "slack.oauth-config",
     lambda m: m["oauth_config"].update(scope=[])),
    ("bot_optional scope missing from bot", "slack.optional-scopes",
     lambda m: m["oauth_config"]["scopes"].update(bot_optional=["pins:read"])),
    ("functions declared with org_deploy_enabled false", "slack.org-deploy",
     lambda m: m.update(functions={})),
]
base_findings = sm.validate(BASE, TABLE)
if base_findings:
    print(f"NO VERDICT on section 3: the baseline manifest is itself invalid ({base_findings}); "
          "no negative control below would mean anything")
    FAILS.append("section 3 baseline invalid")
else:
    for label, rule, fn in CONTROLS:
        got = sm.validate(mutated(fn), TABLE)
        check([r for r, _ in got] == [rule], f"3 {label} -> exactly one {rule} finding (got {[r for r, _ in got]})")
    covered = {r for _, r, _ in CONTROLS}
    check(covered == set(sm.RULES),
          "3z every rule has a negative control, and every control names a rule: "
          f"uncovered {sorted(set(sm.RULES) - covered)}, unknown {sorted(covered - set(sm.RULES))}")

# ---------------------------------------------------------------- 4. CLI
code, out, err = run("generate", "--tier", "minimal", "--name", "n" * 36)
check(code == 2 and out == "" and "slack.name" in err, "4a generate refuses an over-long name: exit 2, empty stdout")
code, out, _ = run("generate", "--tier", "full", "--name", "Ada")
check(code == 0 and json.loads(out)["oauth_config"]["scopes"]["bot"] == sm.tier_scopes(TABLE, "full"),
      "4b generate prints the full-tier manifest as JSON")
code, out, _ = run("generate", "--tier", "minimal", "--name", "Ada", "--url")
check(code == 0 and out.startswith("https://api.slack.com/apps?new_app=1&manifest_json=%7B"),
      "4c generate --url prints the prefilled creation link")
with tempfile.TemporaryDirectory() as td:
    good, bad = os.path.join(td, "good.json"), os.path.join(td, "bad.json")
    for path, doc in ((good, BASE), (bad, mutated(CONTROLS[0][2]))):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
    check(run("validate", good)[0] == 0, "4d validate: a valid manifest exits 0")
    code, out, _ = run("validate", bad)
    check(code == 1 and "channels:fly" in out, "4e validate: an invalid manifest exits 1 naming the scope")
    check(run("validate", os.path.join(td, "absent.json"))[0] == 2, "4f validate: an unreadable file exits 2")
std = sm.tier_scopes(TABLE, "standard")
resp = ("HTTP/2 200\r\ncontent-type: application/json\r\nx-oauth-scopes: " + ",".join(std)
        + '\r\n\r\n{"ok":true,"url":"https://acme.slack.com/","team":"Acme","user":"ada"}\n')
check(run("granted", "--tier", "standard", stdin=resp)[0] == 0, "4g granted: the tier's own scopes exit 0")
code, out, _ = run("granted", "--tier", "minimal", stdin=resp)
check(code == 1 and "extra   im:history" in out, "4h granted: a wider token exits 1 naming the extras")
code, _, err = run("granted", "--tier", "minimal", stdin="curl: (6) Could not resolve host\n")
check(code == 2 and "NO VERDICT" in err, "4i granted: a call that never reached Slack is NO VERDICT, exit 2")
refused = 'HTTP/2 200\r\nx-oauth-scopes: \r\n\r\n{"ok":false,"error":"invalid_auth"}\n'
code, out, err = run("granted", "--tier", "minimal", stdin=refused)
check(code == 2 and "invalid_auth" in err and "missing" not in out,
      "4j granted: a refused token is NO VERDICT naming Slack's error, never 'missing every scope'")

print()
if FAILS:
    print(f"{len(FAILS)} CHECK(S) FAILED")
    sys.exit(1)
print("ALL CHECKS PASSED")
