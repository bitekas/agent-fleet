#!/usr/bin/env python3
"""slack_manifest.py - the Slack app manifest for one fleet agent, and the checks it passes.

Modes (one script, one mode argument):

  tiers [--tier T]
      Print the scope table as markdown: each tier's scopes with a one-line why,
      then the abilities only a USER token has, which no tier requests. This is
      what the person reads before choosing a tier.
  generate --tier T --name NAME [--display-name NAME] [--description TEXT] [--url]
      Print the manifest JSON for tier T (minimal | standard | full). With --url,
      print instead the "create an app from this manifest" link Slack documents.
      The manifest is validated before anything is printed; a manifest that fails
      prints its findings to stderr, nothing to stdout, and exits 2.
  validate FILE
      Check a manifest JSON file against the rules below. Exit 0 valid, 1 not.
  granted --tier T
      Read the whole response of an auth.test call on stdin (curl -sS -D-: the
      headers, then the body) and compare the token's x-oauth-scopes header with
      tier T: prints every scope missing and every scope extra. Exit 0 equal,
      1 different, 2 NO VERDICT. It needs POSITIVE evidence that the call was
      authenticated - the body's "ok":true - before it compares anything:
      without it the input is a call that never reached Slack (a typo'd token
      path, no network) or one Slack refused (invalid_auth), and reading either
      as "the token is missing every scope" would send a person to fix the app
      when the token file is what is wrong.

Exit codes: 0 ok; 1 a finding (validate, granted); 2 usage error, unreadable
input, a refused generate, or granted with nothing to measure.

THE VALIDATOR is a local, stdlib reimplementation of the SHAPE of Slack's app
manifest schema - the keys, types, length limits and the scope vocabulary -
and every rule cites the Slack page it comes from (RULES below). It is not
Slack's validator and does not replace the check Slack runs when the app is
created; it exists so a manifest that would be refused, or accepted and then
quietly break the agent, is caught here before a person pastes it. Two rule
families:

  slack.*   Slack's documented schema. A manifest failing one is refused by
            Slack, or carries a scope Slack would refuse for a bot token.
  fleet.*   This skill's own profile for an agent that POLLS the Web API. A
            manifest failing one is accepted by Slack and then breaks the agent:
            token rotation expires the bot token every 12 hours and cannot be
            turned off again; Socket Mode and event subscriptions need a client
            the watcher does not run; a Messages tab without the DM scopes lets
            people write to a bot that can never read them.

THE SCOPE VOCABULARY is slack-scopes.json beside this file, the checked-in
table with one source URL per scope. A scope absent from it is refused even if
Slack knows it: an unvetted scope is the failure mode the table exists to stop,
and a validator that accepted any well-formed string would accept the typo too.

Stdlib only, no network: generate, validate and the test never call Slack.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
SCOPES_FILE = os.path.join(HERE, "slack-scopes.json")
TIERS = ("minimal", "standard", "full")

MANIFEST_REF = "https://docs.slack.dev/reference/app-manifest"
SCOPES_REF = "https://docs.slack.dev/reference/scopes"
CREATE_REF = "https://docs.slack.dev/app-manifests/configuring-apps-with-app-manifests"
ROTATION_REF = "https://docs.slack.dev/authentication/using-token-rotation"
TOKENS_REF = "https://docs.slack.dev/authentication/tokens"
APP_HOME_REF = "https://docs.slack.dev/surfaces/app-home"
OAUTH_REF = "https://docs.slack.dev/authentication/installing-with-oauth"
SKILL_REF = "SKILL.md section 4 (this skill)"

# rule id -> (source, what it requires). Checked 2026-11-06 against the pages named.
RULES = {
    "slack.top-level-keys": (MANIFEST_REF, "the manifest is a JSON object whose top-level keys are documented manifest sections"),
    "slack.display-information": (MANIFEST_REF, "display_information is required and is an object holding only name, description, long_description, background_color"),
    "slack.name": (MANIFEST_REF, "display_information.name is required: a non-empty string of at most 35 characters"),
    "slack.description": (MANIFEST_REF, "display_information.description, when present, is a string of at most 140 characters"),
    "slack.long-description": (MANIFEST_REF, "display_information.long_description, when present, is a string of 175 to 4000 characters"),
    "slack.background-color": (MANIFEST_REF, "display_information.background_color, when present, is a 3- or 6-digit hex colour with its #"),
    "slack.features": (MANIFEST_REF, "features, when present, is an object whose keys are documented features"),
    "slack.bot-user": (MANIFEST_REF, "features.bot_user holds a required display_name (a non-empty string of at most 80 characters) and an optional boolean always_online, nothing else"),
    "slack.app-home": (MANIFEST_REF, "features.app_home holds only the booleans home_tab_enabled, messages_tab_enabled, messages_tab_read_only_enabled"),
    "slack.oauth-config": (MANIFEST_REF, "oauth_config, when present, is an object whose keys are documented; scopes holds only bot, user, bot_optional, user_optional, each an array of at most 255 strings"),
    "slack.optional-scopes": (MANIFEST_REF, "every scope in bot_optional (user_optional) is also listed in bot (user)"),
    "slack.scope-known": (SCOPES_REF, "every scope is a Slack scope listed, with its source page, in slack-scopes.json"),
    "slack.scope-token-type": (SCOPES_REF, "a scope under bot is one Slack grants a Bot token; a scope under user is one Slack grants a User token"),
    "slack.settings": (MANIFEST_REF, "settings, when present, is an object whose keys are documented settings, and its documented booleans are booleans"),
    "slack.org-deploy": (MANIFEST_REF, "settings.org_deploy_enabled is true when the manifest declares functions, workflows, datastores, types, outgoing_domains or events"),
    "fleet.polling-profile": (SKILL_REF + "; " + ROTATION_REF + "; " + TOKENS_REF,
                              "settings sets socket_mode_enabled, org_deploy_enabled and token_rotation_enabled, each false, and declares no event_subscriptions; features.bot_user is present"),
    "fleet.dm-reachable": (APP_HOME_REF, "a writable Messages tab and the im:read + im:history bot scopes come together: neither without the other"),
}

TOP_LEVEL = {"_metadata", "display_information", "settings", "features", "oauth_config",
             "functions", "workflows", "datastores", "outgoing_domains", "types", "events",
             "external_auth_providers", "compliance", "mcp_servers", "app_directory"}
DISPLAY_KEYS = {"name", "description", "long_description", "background_color"}
FEATURES = {"agent_view", "app_home", "assistant_view", "bot_user", "code_channels",
            "rich_previews", "search", "shortcuts", "slash_commands", "unfurl_domains",
            "workflow_steps"}
APP_HOME_KEYS = {"home_tab_enabled", "messages_tab_enabled", "messages_tab_read_only_enabled"}
OAUTH_KEYS = {"scopes", "redirect_urls", "token_management_enabled", "pkce_enabled",
              "is_enterprise_managed_auth_supported"}
SCOPE_LISTS = {"bot": "Bot", "user": "User", "bot_optional": "Bot", "user_optional": "User"}
SETTINGS_KEYS = {"allowed_ip_address_ranges", "app_level_token_rotation_enabled",
                 "event_subscriptions", "incoming_webhooks", "interactivity",
                 "org_deploy_enabled", "socket_mode_enabled", "token_rotation_enabled",
                 "is_hosted", "is_mcp_enabled", "siws_links", "function_runtime"}
SETTINGS_BOOLS = {"app_level_token_rotation_enabled", "org_deploy_enabled", "socket_mode_enabled",
                  "token_rotation_enabled", "is_hosted", "is_mcp_enabled"}
NEEDS_ORG_DEPLOY = ("functions", "workflows", "datastores", "types", "outgoing_domains", "events")
FLEET_FALSE = ("socket_mode_enabled", "org_deploy_enabled", "token_rotation_enabled")
HEX = re.compile(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def load_table(path=SCOPES_FILE):
    """The scope table, keyed by scope name. Raises on a malformed row, because a
    table that loads half its rows would make every scope it dropped read as
    invented - a refusal whose stated reason is false."""
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)["scopes"]
    table = {}
    for r in rows:
        if r.get("tier") not in TIERS + (None,) or not r.get("why") or not r.get("source"):
            raise ValueError(f"{path}: malformed row {r!r}")
        table[r["scope"]] = r
    # A tier with no row would generate a manifest with no new scopes that still
    # validates (an empty scope list breaks no Slack rule), so refuse it here.
    for t in TIERS:
        if not any(r["tier"] == t for r in table.values()):
            raise ValueError(f"{path}: no row for tier {t}")
    return table


def tier_scopes(table, tier):
    """The bot scopes tier T requests, in table order. Tiers are cumulative."""
    upto = TIERS[: TIERS.index(tier) + 1]
    return [s for s, r in table.items() if r["tier"] in upto]


def validate(m, table):
    """Every violation as (rule id, message). An empty list is a valid manifest."""
    out = []

    def bad(rule, msg):
        out.append((rule, msg))

    if not isinstance(m, dict):
        return [("slack.top-level-keys", "the manifest is not a JSON object")]
    for k in sorted(set(m) - TOP_LEVEL):
        bad("slack.top-level-keys", f"unknown top-level key {k!r}")

    di = m.get("display_information")
    if not isinstance(di, dict):
        bad("slack.display-information", "display_information is missing or not an object")
        di = {}
    for k in sorted(set(di) - DISPLAY_KEYS):
        bad("slack.display-information", f"unknown key display_information.{k}")
    name = di.get("name")
    if not isinstance(name, str) or not name.strip():
        bad("slack.name", "display_information.name is missing or empty")
    elif len(name) > 35:
        bad("slack.name", f"display_information.name is {len(name)} characters; the limit is 35")
    if "description" in di and not (isinstance(di["description"], str) and len(di["description"]) <= 140):
        bad("slack.description", "display_information.description is not a string of at most 140 characters")
    if "long_description" in di and not (isinstance(di["long_description"], str)
                                         and 175 <= len(di["long_description"]) <= 4000):
        bad("slack.long-description", "display_information.long_description is not a string of 175 to 4000 characters")
    if "background_color" in di and not (isinstance(di["background_color"], str)
                                         and HEX.match(di["background_color"])):
        bad("slack.background-color", "display_information.background_color is not #rgb or #rrggbb")

    feats = m.get("features", {})
    if not isinstance(feats, dict):
        bad("slack.features", "features is not an object")
        feats = {}
    for k in sorted(set(feats) - FEATURES):
        bad("slack.features", f"unknown key features.{k}")
    bu = feats.get("bot_user")
    if bu is not None:
        dn = bu.get("display_name") if isinstance(bu, dict) else None
        if not isinstance(bu, dict) or set(bu) - {"display_name", "always_online"}:
            bad("slack.bot-user", "features.bot_user is not an object of display_name and always_online")
        if not isinstance(dn, str) or not dn.strip() or len(dn) > 80:
            bad("slack.bot-user", "features.bot_user.display_name is missing, empty or over 80 characters")
        if isinstance(bu, dict) and not isinstance(bu.get("always_online", False), bool):
            bad("slack.bot-user", "features.bot_user.always_online is not a boolean")
    ah = feats.get("app_home")
    if ah is not None and not (isinstance(ah, dict) and set(ah) <= APP_HOME_KEYS
                               and all(isinstance(v, bool) for v in ah.values())):
        bad("slack.app-home", "features.app_home holds a key or value outside its three booleans")

    oc = m.get("oauth_config", {})
    lists = {}
    if not isinstance(oc, dict):
        bad("slack.oauth-config", "oauth_config is not an object")
        oc = {}
    for k in sorted(set(oc) - OAUTH_KEYS):
        bad("slack.oauth-config", f"unknown key oauth_config.{k}")
    sc = oc.get("scopes", {})
    if not isinstance(sc, dict):
        bad("slack.oauth-config", "oauth_config.scopes is not an object")
        sc = {}
    for k, v in sc.items():
        if k not in SCOPE_LISTS:
            bad("slack.oauth-config", f"unknown key oauth_config.scopes.{k}")
        elif not (isinstance(v, list) and all(isinstance(s, str) for s in v) and len(v) <= 255):
            bad("slack.oauth-config", f"oauth_config.scopes.{k} is not an array of at most 255 strings")
        else:
            lists[k] = v
    for opt, base in (("bot_optional", "bot"), ("user_optional", "user")):
        for s in sorted(set(lists.get(opt, [])) - set(lists.get(base, []))):
            bad("slack.optional-scopes", f"{s!r} is in scopes.{opt} but not in scopes.{base}")
    for k, v in lists.items():
        for s in v:
            row = table.get(s)
            if row is None:
                bad("slack.scope-known", f"{s!r} (scopes.{k}) is not a Slack scope in slack-scopes.json")
            elif SCOPE_LISTS[k] not in row["token_types"]:
                bad("slack.scope-token-type",
                    f"{s!r} (scopes.{k}) is granted to {'/'.join(row['token_types'])} tokens only, not {SCOPE_LISTS[k]}")

    st = m.get("settings", {})
    if not isinstance(st, dict):
        bad("slack.settings", "settings is not an object")
        st = {}
    for k in sorted(set(st) - SETTINGS_KEYS):
        bad("slack.settings", f"unknown key settings.{k}")
    for k in sorted(SETTINGS_BOOLS & set(st)):
        if not isinstance(st[k], bool):
            bad("slack.settings", f"settings.{k} is not a boolean")
    needs = [k for k in NEEDS_ORG_DEPLOY if k in m]
    if needs and st.get("org_deploy_enabled") is not True:
        bad("slack.org-deploy", f"{', '.join(needs)} declared without settings.org_deploy_enabled true")

    for k in FLEET_FALSE:
        if st.get(k) is not False:
            bad("fleet.polling-profile", f"settings.{k} must be present and false for a polling agent")
    if "event_subscriptions" in st:
        bad("fleet.polling-profile", "settings.event_subscriptions is declared; a polling agent reads the Web API instead")
    if bu is None:
        bad("fleet.polling-profile", "features.bot_user is missing; the agent posts as its bot user")
    dm_tab = isinstance(ah, dict) and ah.get("messages_tab_enabled") is True \
        and ah.get("messages_tab_read_only_enabled") is not True
    dm_scopes = {"im:read", "im:history"} <= set(lists.get("bot", []))
    if dm_tab != dm_scopes:
        bad("fleet.dm-reachable", "a writable Messages tab without im:read + im:history" if dm_tab
            else "im:read + im:history without a writable Messages tab, so nobody can open a DM with it")
    return out


def build(tier, name, display_name=None, description=None, table=None):
    """The manifest for tier T. Nothing else: no event subscriptions, no Socket
    Mode, no token rotation, no org-wide deploy (fleet.polling-profile says why)."""
    table = table or load_table()
    dms = "im:history" in tier_scopes(table, tier)
    di = {"name": name}
    if description:
        di["description"] = description
    return {
        "display_information": di,
        "features": {
            "app_home": {"home_tab_enabled": False, "messages_tab_enabled": dms,
                         "messages_tab_read_only_enabled": False},
            "bot_user": {"display_name": display_name or name, "always_online": True},
        },
        "oauth_config": {"scopes": {"bot": tier_scopes(table, tier)}},
        "settings": {"org_deploy_enabled": False, "socket_mode_enabled": False,
                     "token_rotation_enabled": False},
    }


def create_url(manifest):
    """Slack's documented prefilled app-creation link (CREATE_REF, "share the
    manifest in JSON format"), with the JSON URL-encoded as that page requires."""
    body = json.dumps(manifest, separators=(",", ":"))
    return "https://api.slack.com/apps?new_app=1&manifest_json=" + urllib.parse.quote(body, safe="")


def print_findings(findings, stream):
    for rule, msg in findings:
        print(f"{rule}: {msg}  [{RULES[rule][0]}]", file=stream)


def cmd_tiers(table, only):
    tiers = [only] if only else list(TIERS)
    for t in tiers:
        print(f"\n### {t}" + ("" if t == "minimal" else f" (everything in {TIERS[TIERS.index(t) - 1]}, plus)"))
        print("\n| Scope | Why |\n|---|---|")
        for s, r in table.items():
            if r["tier"] == t or (only and r["tier"] in TIERS[: TIERS.index(t)]):
                print(f"| `{s}` | {r['why']} |")
    print("\n### Not available to a bot token in any tier\n\n| Scope | Tokens | What it would allow |\n|---|---|---|")
    for s, r in table.items():
        if r["tier"] is None:
            print(f"| `{s}` | {'/'.join(r['token_types'])} | {r['why']} |")
    return 0


def cmd_granted(table, tier, text):
    ok = re.search(r'"ok"\s*:\s*(true|false)', text)
    hdr = re.search(r"^x-oauth-scopes:[ \t]*(.*?)\s*$", text, re.I | re.M)
    if not ok or ok.group(1) != "true":
        err = re.search(r'"error"\s*:\s*"([a-z_]+)"', text)
        print("NO VERDICT: no authenticated auth.test response in the input"
              + (f" (Slack answered {err.group(1)})" if err else "")
              + " - pipe the whole response: curl -sS -D- https://slack.com/api/auth.test ...",
              file=sys.stderr)
        return 2
    if not hdr or not hdr.group(1):
        print("NO VERDICT: the response carries no x-oauth-scopes header to compare", file=sys.stderr)
        return 2
    have = {s.strip() for s in hdr.group(1).split(",") if s.strip()}
    want = set(tier_scopes(table, tier))
    for s in sorted(want - have):
        print(f"missing {s}")
    for s in sorted(have - want):
        print(f"extra   {s}")
    print(f"{'OK' if have == want else 'DIFFERENT'}: the token holds {len(have)} scopes, tier {tier} requests {len(want)}")
    return 0 if have == want else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="slack_manifest.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("tiers")
    t.add_argument("--tier", choices=TIERS)
    g = sub.add_parser("generate")
    g.add_argument("--tier", choices=TIERS, required=True)
    g.add_argument("--name", required=True, help="the app name (at most 35 characters)")
    g.add_argument("--display-name", help="the bot's display name (default: the app name)")
    g.add_argument("--description", help="one line for display_information.description")
    g.add_argument("--url", action="store_true", help="print the prefilled app-creation link instead")
    v = sub.add_parser("validate")
    v.add_argument("file")
    gr = sub.add_parser("granted")
    gr.add_argument("--tier", choices=TIERS, required=True)
    a = p.parse_args(argv)
    table = load_table()

    if a.mode == "tiers":
        return cmd_tiers(table, a.tier)
    if a.mode == "granted":
        return cmd_granted(table, a.tier, sys.stdin.read())
    if a.mode == "generate":
        m = build(a.tier, a.name, a.display_name, a.description, table)
        findings = validate(m, table)
        if findings:
            print_findings(findings, sys.stderr)
            print("REFUSED: nothing generated", file=sys.stderr)
            return 2
        print(create_url(m) if a.url else json.dumps(m, indent=2))
        return 0
    try:
        with open(a.file, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {a.file}: {e}", file=sys.stderr)
        return 2
    findings = validate(m, table)
    print_findings(findings, sys.stdout)
    print("VALID" if not findings else f"INVALID: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
