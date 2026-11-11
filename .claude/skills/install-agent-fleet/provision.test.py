#!/usr/bin/env python3
"""provision.test.py - the least-privilege policies and provision.py, offline.

Usage: python3 .claude/skills/install-agent-fleet/provision.test.py
       (tests/run-all.sh discovers and runs it; no network, no cloud call)

What it proves:
  1. Shape. policies/aws-one-vm.json follows the IAM policy grammar this file
     uses (Version, Statement[] of Sid/Effect/Action/Resource/Condition, no
     NotAction or NotResource); policies/gcp-one-vm-role.json carries exactly
     the custom-role fields gcloud reads (title, description, stage,
     includedPermissions).
  2. The sources table. Every action, condition key and permission in a policy
     has a row in policies/README.md naming an official page and a check date,
     and every row names one that is in the policy.
  3. No wildcard. No action or permission holds `*` or `?`, and `Resource: "*"`
     appears only on EC2 Describe actions, which define no resource type.
  4. --dry-run renders the expected commands (size, image, region, tags or
     labels, the SSH rule restricted to the given range) as a script bash can
     parse, and runs nothing: fake aws, gcloud and ssh on PATH record every
     call, and a dry run leaves no record.
  5. --apply runs exactly the dry run's commands, in order, with the captured
     values substituted, and every provider call carries the dedicated profile
     or configuration; a failing step stops the run before the next one.
  6. Refusals: an SSH range open to the world, wider than /24 or IPv6, a
     private key path, a bad name - exit 2 with NOTHING run, under --apply.
  7. Credentials: a canary in a fake credential store (mode 000) never reaches
     the output, and the run succeeds without reading it.

THE CONTROLS, and why each is here. Checks 1 to 3 are functions; before they
judge the real files they judge planted faults - a wildcard action, an
`ec2:Describe*`, a missing and an extra table row, `Resource: "*"` on a write
action, a NotAction statement, a wildcard and an unknown field in the role -
and each must come back as a finding. A control that does not fire means the
checker cannot see the fault class it claims, so the run issues NO VERDICT
(exit 3) instead of a pass: a green from a blind checker is the one result
this file must never print. Checks 4 to 7 compare against a recorded call log;
their control is that the same log is NON-EMPTY after a successful --apply, so
an empty log after a dry run or a refusal means "nothing ran", not "the fake
never recorded".

Exit codes: 0 every check passed and every control fired; 1 a check failed;
3 NO VERDICT (a control did not fire, or the fixture could not be built).
"""

import copy
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "provision.py"
POLICIES = HERE / "policies"
AWS_FILE, GCP_FILE = "aws-one-vm.json", "gcp-one-vm-role.json"
WILD = re.compile(r"[*?]")
failures, noverdict = [], []


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


# ------------------------------------------------------------ the checkers

def as_list(v):
    return v if isinstance(v, list) else [v]


def aws_findings(pol, table):
    """Findings for an AWS policy against its table {'action': set, 'key': set}."""
    out = []
    if pol.get("Version") != "2012-10-17":
        out.append("Version is not 2012-10-17")
    stmts = pol.get("Statement")
    if not isinstance(stmts, list) or not stmts:
        return out + ["Statement is not a non-empty list"]
    if set(pol) - {"Version", "Statement"}:
        out.append(f"unknown top-level key(s) {sorted(set(pol) - {'Version', 'Statement'})}")
    actions, keys = set(), set()
    for i, st in enumerate(stmts):
        where = f"Statement[{i}] {st.get('Sid', '')}"
        extra = set(st) - {"Sid", "Effect", "Action", "Resource", "Condition"}
        if extra:
            out.append(f"{where}: field(s) outside the grammar this policy uses: {sorted(extra)}")
        if st.get("Effect") not in ("Allow", "Deny"):
            out.append(f"{where}: Effect is not Allow or Deny")
        acts, res = st.get("Action"), st.get("Resource")
        if acts is None or res is None:
            out.append(f"{where}: needs both Action and Resource")
            continue
        for a in as_list(acts):
            if not isinstance(a, str) or not re.fullmatch(r"ec2:[A-Za-z*?]+", a):
                out.append(f"{where}: action {a!r} is not an ec2:<Action> name")
            if isinstance(a, str) and WILD.search(a):
                out.append(f"{where}: action {a!r} is a wildcard")
            actions.add(a)
        for r in as_list(res):
            if r != "*" and not (isinstance(r, str) and r.startswith("arn:aws:ec2:")):
                out.append(f"{where}: resource {r!r} is neither * nor an EC2 ARN")
        if "*" in as_list(res):
            writes = [a for a in as_list(acts) if not str(a).startswith("ec2:Describe")]
            if writes:
                out.append(f"{where}: Resource * on {writes}; only Describe actions, which define no "
                           f"resource type, may take it")
        cond = st.get("Condition", {})
        if not isinstance(cond, dict):
            out.append(f"{where}: Condition is not an object")
            continue
        for op, body in cond.items():
            if not isinstance(body, dict) or not body:
                out.append(f"{where}: Condition {op} is not a non-empty object")
                continue
            for k, v in body.items():
                keys.add(k)
                if not all(isinstance(x, str) and x for x in as_list(v)):
                    out.append(f"{where}: Condition {op} {k} has a non-string value")
    out += [f"action {a} is not in the sources table" for a in sorted(actions - table["action"])]
    out += [f"sources table row {a} is not in the policy" for a in sorted(table["action"] - actions)]
    out += [f"condition key {k} is not in the sources table" for k in sorted(keys - table["key"])]
    out += [f"sources table row {k} is not in the policy" for k in sorted(table["key"] - keys)]
    return out


def gcp_findings(role, table):
    out = []
    want = {"title", "description", "stage", "includedPermissions"}
    if set(role) != want:
        out.append(f"fields {sorted(role)} are not exactly {sorted(want)}")
    if role.get("stage") not in ("ALPHA", "BETA", "GA", "DEPRECATED", "DISABLED", "EAP"):
        out.append(f"stage {role.get('stage')!r} is not a custom-role stage")
    for f in ("title", "description"):
        if not isinstance(role.get(f), str) or not role.get(f):
            out.append(f"{f} is not a non-empty string")
    perms = role.get("includedPermissions")
    if not isinstance(perms, list) or not perms:
        return out + ["includedPermissions is not a non-empty list"]
    for p in perms:
        if not isinstance(p, str) or not re.fullmatch(r"compute\.[A-Za-z*?]+\.[A-Za-z*?]+", p):
            out.append(f"permission {p!r} is not a compute.<resource>.<verb> name")
        if isinstance(p, str) and WILD.search(p):
            out.append(f"permission {p!r} is a wildcard")
    if len(set(perms)) != len(perms):
        out.append("includedPermissions repeats a permission")
    have = set(perms)
    out += [f"permission {p} is not in the sources table" for p in sorted(have - table["permission"])]
    out += [f"sources table row {p} is not in the policy" for p in sorted(table["permission"] - have)]
    return out


def parse_table(text):
    """{file: {'action'|'key'|'permission': set}} from the README's tables.
    A table belongs to the last `## ... `<file>`` heading above it; its kind is
    its header's first cell. A row needs an https:// page and a YYYY-MM-DD date."""
    tables, problems, file, kind = {}, [], None, None
    kinds = {"Action": "action", "Condition key": "key", "Permission": "permission"}
    for no, line in enumerate(text.split("\n"), 1):
        m = re.match(r"## .*`([^`]+\.json)`", line)
        if m:
            file, kind = m.group(1), None
            tables[file] = {"action": set(), "key": set(), "permission": set()}
            continue
        if line.startswith("## "):
            file, kind = None, None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if not cells or file is None:
            continue
        if cells[0] in kinds:
            kind = kinds[cells[0]]
            continue
        n = re.fullmatch(r"`([^`]+)`", cells[0])
        if not n or kind is None:
            continue
        if len(cells) != 4 or not cells[2].startswith("https://") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[3]):
            problems.append(f"README.md:{no}: row for {n.group(1)} needs 4 cells, an https:// page and a "
                            f"YYYY-MM-DD check date")
        tables[file][kind].add(n.group(1))
    return tables, problems


# ---------------------------------------------------------------- 1 to 3

def policy_checks():
    aws = json.loads((POLICIES / AWS_FILE).read_text(encoding="utf-8"))
    gcp = json.loads((POLICIES / GCP_FILE).read_text(encoding="utf-8"))
    tables, problems = parse_table((POLICIES / "README.md").read_text(encoding="utf-8"))
    if AWS_FILE not in tables or GCP_FILE not in tables:
        noverdict.append(f"README.md has no table section for {AWS_FILE} and {GCP_FILE}")
        return
    ta, tg = tables[AWS_FILE], tables[GCP_FILE]
    if not ta["action"] or not ta["key"] or not tg["permission"]:
        noverdict.append("a README.md table parsed empty, so the table comparison would pass vacuously")
        return

    # The controls: each planted fault must be reported by the checker that claims its class.
    def aws_mut(f):
        p = copy.deepcopy(aws)
        f(p)
        return p

    first_action = sorted(ta["action"])[0]
    controls = [
        ("a wildcard action", aws_findings(aws_mut(lambda p: p["Statement"].append(
            {"Effect": "Allow", "Action": "ec2:*", "Resource": "arn:aws:ec2:*:*:instance/*"})), ta), "is a wildcard"),
        ("a Describe* action", aws_findings(aws_mut(lambda p: p["Statement"][0]["Action"].append(
            "ec2:Describe*")), ta), "'ec2:Describe*' is a wildcard"),
        ("a policy action missing from the table",
         aws_findings(aws, {"action": ta["action"] - {first_action}, "key": ta["key"]}),
         f"action {first_action} is not in the sources table"),
        ("a table row missing from the policy",
         aws_findings(aws, {"action": ta["action"] | {"ec2:DeleteVolume"}, "key": ta["key"]}),
         "sources table row ec2:DeleteVolume is not in the policy"),
        ("Resource * on a write action", aws_findings(aws_mut(lambda p: p["Statement"].append(
            {"Effect": "Allow", "Action": "ec2:RunInstances", "Resource": "*"})), ta), "Resource * on"),
        ("a NotAction statement", aws_findings(aws_mut(lambda p: p["Statement"].append(
            {"Effect": "Allow", "NotAction": "iam:CreateUser", "Resource": "*"})), ta), "outside the grammar"),
        ("a wildcard permission", gcp_findings(dict(gcp, includedPermissions=gcp["includedPermissions"] + [
            "compute.instances.*"]), tg), "is a wildcard"),
        ("a role permission missing from the table",
         gcp_findings(gcp, {"permission": tg["permission"] - {"compute.instances.create"}}),
         "compute.instances.create is not in the sources table"),
        ("an unknown role field", gcp_findings(dict(gcp, etag="x"), tg), "are not exactly"),
    ]
    for name, found, expect in controls:
        if any(expect in f for f in found):
            print(f"ok    control fired: {name}")
        else:
            noverdict.append(f"control did not fire: {name} (expected a finding containing {expect!r}; "
                             f"got {found})")
    if noverdict:
        return
    check(not problems, "every README.md table row names an https:// page and a check date" +
          ("" if not problems else ": " + "; ".join(problems)))
    fa = aws_findings(aws, ta)
    check(not fa, f"{AWS_FILE}: grammar, no wildcard, table both ways" + ("" if not fa else ": " + "; ".join(fa)))
    fg = gcp_findings(gcp, tg)
    check(not fg, f"{GCP_FILE}: fields, no wildcard, table both ways" + ("" if not fg else ": " + "; ".join(fg)))


# ---------------------------------------------------------------- 4 to 7

FAKE = r'''#!PYTHON
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([name] + sys.argv[1:]) + "\n")
words = " ".join(sys.argv[1:])
fail = os.environ.get("FAKE_FAIL", "")
if fail and fail in words:
    sys.stderr.write("fake failure for " + fail + "\n")
    sys.exit(1)
answers = {"describe-images": "ami-0abcdef1234567890", "run-instances": "i-0abcdef1234567890",
           "describe-instances": "203.0.113.50", "instances describe": "203.0.113.51"}
for k, v in answers.items():
    if k in words:
        print(os.environ.get("FAKE_" + k.replace(" ", "_").replace("-", "_").upper(), v))
'''


class Rig:
    def __init__(self, root):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        for name in ("aws", "gcloud", "ssh"):
            p = self.bin / name
            p.write_text(FAKE.replace("PYTHON", sys.executable), encoding="utf-8")
            p.chmod(0o755)
        self.log = root / "calls.jsonl"
        self.home = root / "home"
        for rel in (".aws/credentials", ".config/gcloud/credentials.db"):
            f = self.home / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("aws_secret_access_key = CANARY-not-a-real-secret-7f3a\n", encoding="utf-8")
            f.chmod(0)
            f.parent.chmod(0)
        self.key = root / "id_test.pub"
        self.key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTestsOnly0000000000000000000000 "
                            "ada@example.com\n", encoding="utf-8")

    def run(self, provider, *extra, mode="--dry-run", fail=None, region=None):
        if self.log.exists():
            self.log.unlink()
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                   HOME=str(self.home), FAKE_LOG=str(self.log))
        env.pop("FAKE_FAIL", None)
        if fail:
            env["FAKE_FAIL"] = fail
        argv = [sys.executable, str(SCRIPT), "--provider", provider, "--name", "fleet-test",
                "--region", region or ("eu-central-1" if provider == "aws" else "europe-west1"),
                "--ssh-public-key", str(self.key), mode, "--wait-ssh", "5"]
        if provider == "gcp":
            argv += ["--project", "example-project"]
        if "--ssh-cidr" not in extra:
            argv += ["--ssh-cidr", "203.0.113.7/32"]
        r = subprocess.run(argv + list(extra), capture_output=True, text=True, env=env, timeout=120)
        calls = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return r, calls

    def cleanup(self):
        for d in (self.home / ".aws", self.home / ".config/gcloud"):
            d.chmod(0o755)
            for f in d.iterdir():
                f.chmod(0o644)


def dry_lines(out, values):
    """The dry run's command lines as argv lists, with captured values substituted."""
    cmds = []
    for line in out.split("\n"):
        if not line or line.startswith("#") or line == "set -eu":
            continue
        m = re.fullmatch(r"([A-Z_]+)=\$\((.*)\)", line)
        body = m.group(2) if m else line
        for k, v in values.items():
            body = body.replace(f'"${{{k}}}"', shlex.quote(v))
        cmds.append(shlex.split(body))
    return cmds


EXPECT = {
    "aws": ["aws ec2 describe-images --profile agent-fleet --region eu-central-1 --owners 099720109477",
            "ubuntu/images/hvm-ssd-gp3/ubuntu-resolute-26.04-amd64-server-*",
            "--instance-type t3.xlarge",
            "VolumeSize=100,VolumeType=gp3",
            "ResourceType=instance,Tags=[{Key=Name,Value=fleet-test},{Key=agent-fleet,Value=managed}]",
            "ResourceType=volume,Tags=",
            "ResourceType=security-group,Tags=",
            "ResourceType=key-pair,Tags=",
            "authorize-security-group-ingress --profile agent-fleet --region eu-central-1 --group-name "
            "fleet-test-ssh --protocol tcp --port 22 --cidr 203.0.113.7/32"],
    "gcp": ["gcloud compute firewall-rules create fleet-test-ssh --configuration=agent-fleet "
            "--project=example-project --network=default --direction=INGRESS --action=ALLOW --rules=tcp:22 "
            "--source-ranges=203.0.113.7/32 --target-tags=fleet-test-ssh",
            "--zone=europe-west1-b", "--machine-type=e2-standard-4",
            "--image-family=ubuntu-2604-lts-amd64 --image-project=ubuntu-os-cloud",
            "--boot-disk-size=100GB --boot-disk-type=pd-balanced", "--tags=fleet-test-ssh",
            "--labels=agent-fleet=managed", "--no-service-account --no-scopes"],
}
CAPTURED = {"aws": {"IMAGE_ID": "ami-0abcdef1234567890", "INSTANCE_ID": "i-0abcdef1234567890",
                    "PUBLIC_IP": "203.0.113.50"},
            "gcp": {"PUBLIC_IP": "203.0.113.51"}}


def script_checks(rig):
    for prov in ("aws", "gcp"):
        r, calls = rig.run(prov)
        check(r.returncode == 0, f"{prov} --dry-run exits 0 (got {r.returncode}: {r.stderr.strip()[:200]})")
        for e in EXPECT[prov]:
            check(e in r.stdout, f"{prov} --dry-run renders: {e}")
        check("0.0.0.0/0" not in r.stdout, f"{prov} --dry-run opens nothing to 0.0.0.0/0")
        check(calls == [], f"{prov} --dry-run ran nothing (calls recorded: {len(calls)})")
        bash = shutil.which("bash")
        n = subprocess.run([bash, "-n"], input=r.stdout, capture_output=True, text=True) if bash else None
        check(n is not None and n.returncode == 0,
              f"{prov} --dry-run output parses as bash ({'no bash on PATH' if n is None else n.stderr.strip()[:200]})")

        ra, calls = rig.run(prov, mode="--apply")
        check(ra.returncode == 0, f"{prov} --apply against fake CLIs exits 0 (got {ra.returncode}: "
                                  f"{ra.stderr.strip()[:300]})")
        if not calls:
            noverdict.append(f"{prov} --apply recorded no call, so 'a dry run recorded none' proves nothing")
            continue
        want = dry_lines(r.stdout, CAPTURED[prov])
        check(calls == want, f"{prov} --apply ran exactly the dry run's commands, in order "
                             f"({len(calls)} recorded, {len(want)} rendered)")
        if calls != want:
            for c, w in zip(calls, want):
                if c != w:
                    print(f"      first difference:\n        ran      {c}\n        rendered {w}")
                    break
        flag = "--profile" if prov == "aws" else "--configuration=agent-fleet"
        provider_calls = [c for c in calls if c[0] != "ssh"]
        check(bool(provider_calls) and all((flag in c and c[c.index(flag) + 1] == "agent-fleet") if prov == "aws"
                                           else flag in c for c in provider_calls),
              f"{prov} every provider call names the dedicated {flag} ({len(provider_calls)} call(s))")
        check(f"READY: ssh ubuntu@{CAPTURED[prov]['PUBLIC_IP']}" in ra.stdout, f"{prov} --apply ends READY")
        out = ra.stdout + ra.stderr + r.stdout + r.stderr
        check("CANARY" not in out, f"{prov}: nothing from the credential store reaches the output")

    # A failing step stops the run: nothing after it is called.
    rf, calls = rig.run("aws", mode="--apply", fail="create-security-group")
    names = [c[2] for c in calls]
    check(rf.returncode == 1 and "FAILED at step 3" in rf.stderr,
          f"a failing step exits 1 and names itself (got {rf.returncode}: {rf.stderr.strip()[:200]})")
    check("run-instances" not in names and names[-1:] == ["create-security-group"],
          f"nothing runs after the failing step (called: {names})")
    os.environ["FAKE_DESCRIBE_IMAGES"] = "None"
    try:
        rn, calls = rig.run("aws", mode="--apply")
    finally:
        del os.environ["FAKE_DESCRIBE_IMAGES"]
    check(rn.returncode == 1 and "printed no value for IMAGE_ID" in rn.stderr and len(calls) == 1,
          f"no Ubuntu image found stops at step 1 (got {rn.returncode}, {len(calls)} call(s))")

    # Refusals: exit 2 and nothing run, even under --apply.
    refusals = [
        (("--ssh-cidr", "0.0.0.0/0"), "wider than /24"),
        (("--ssh-cidr", "10.0.0.0/8"), "wider than /24"),
        (("--ssh-cidr", "2001:db8::/64"), "IPv4 only"),
        (("--ssh-cidr", "not-an-address"), "not an IPv4 address"),
        (("--ssh-public-key", str(rig.root / "id_test")), "not a .pub file"),
        (("--name", "Bad_Name"), "lowercase letters"),
    ]
    for prov in ("aws", "gcp"):
        for extra, why in refusals:
            # --name and --ssh-public-key are then given twice; argparse keeps the last one
            rr, calls = rig.run(prov, *extra, mode="--apply")
            check(rr.returncode == 2 and why in rr.stderr and calls == [],
                  f"{prov} refuses {' '.join(extra)}: exit 2, nothing run (got {rr.returncode}, "
                  f"{len(calls)} call(s))")
    rs, _ = rig.run("aws", "--ssh-cidr", "203.0.113.7", mode="--dry-run")
    check("--cidr 203.0.113.7/32" in rs.stdout, "a bare address becomes a /32")


def main():
    policy_checks()
    if not noverdict:
        with tempfile.TemporaryDirectory(prefix="provision-test-") as tmp:
            rig = Rig(Path(tmp))
            try:
                script_checks(rig)
            finally:
                rig.cleanup()
    if noverdict:
        print("NO VERDICT: " + "; ".join(noverdict))
        return 3
    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
