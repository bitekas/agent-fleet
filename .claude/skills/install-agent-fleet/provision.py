#!/usr/bin/env python3
"""provision.py - create ONE agent-fleet VM in AWS or Google Cloud with the
provider's own CLI: its SSH key, a firewall rule admitting SSH from one address
range, the instance with its boot disk, then wait until SSH answers.

Usage:
  python3 provision.py --provider aws --region R --name N --ssh-cidr A.B.C.D[/P]
                       --ssh-public-key PATH.pub (--dry-run | --apply)
                       [--size TYPE] [--disk-gb G] [--profile NAME] [--wait-ssh SECONDS]
  python3 provision.py --provider gcp --project P --region R --name N --ssh-cidr ...
                       --ssh-public-key PATH.pub (--dry-run | --apply)
                       [--zone Z] [--size TYPE] [--disk-gb G] [--configuration NAME]
                       [--wait-ssh SECONDS]

Defaults: --size t3.xlarge (aws) / e2-standard-4 (gcp), --disk-gb 100, --profile
and --configuration agent-fleet, --zone <region>-b, --wait-ssh 600. The image is
Ubuntu 26.04 LTS amd64. The login user is `ubuntu`.

--dry-run prints the commands as a bash script and runs nothing: no provider
CLI, no ssh, no network. --apply prints each command line and runs it, then
waits for SSH and prints a final `READY: ssh ubuntu@<address>` line.

Exit codes: 0 done (dry-run: printed; apply: SSH answers); 1 a step failed,
named, and nothing after it ran; 2 refused before anything ran (usage, a bad
name, a public key path that is not a .pub file, an SSH range wider than /24 or
not IPv4).

Python 3.9 or newer, standard library only: it runs on the person's LOCAL
machine, and 3.9 is the python3 Apple's Command Line Tools install.

LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole:

  * CREDENTIALS NEVER PASS THROUGH THIS SCRIPT. Every command names the CLI's
    own named profile (`--profile`) or configuration (`--configuration`), and
    the CLI reads its own credential store. This script opens no file under
    ~/.aws or ~/.config/gcloud and prints nothing from one. Remove the
    `--profile`/`--configuration` argument and the command runs as whatever
    identity the person's default profile is - typically an administrator -
    and the least-privilege policy stops being the boundary. The test plants a
    canary in a fake credential store and asserts it never reaches the output.

  * ONE STEP LIST FEEDS BOTH MODES. `aws_steps`/`gcp_steps` build the commands
    once; --dry-run renders them and --apply runs the same argv lists. A second
    copy for either mode would let the reviewed dry-run drift from what runs.
    The test runs --apply against fake CLIs and compares every recorded argv
    with the dry-run's lines.

  * THE SSH RANGE IS CHECKED BEFORE ANYTHING RUNS. A rule open to 0.0.0.0/0
    exposes the agents' host to the whole internet, and neither provider's IAM
    can refuse it: no AWS condition key and no GCP permission reads the source
    range of an ingress rule. This check is the only place it is stopped. IPv4
    only, prefix /24 or longer; a bare address is /32.

  * ONLY A .pub PATH IS EVER OPENED. The public key is read to validate it (and,
    for gcp, to put it in instance metadata). A private key path is refused by
    its name, before it is opened, so a mistyped path cannot print a key.
"""

import argparse
import ipaddress
import re
import shlex
import subprocess
import sys
import time

TAG_KEY, TAG_VALUE = "agent-fleet", "managed"
LOGIN_USER = "ubuntu"
# Canonical's publisher account for Ubuntu AMIs, and the AMI name pattern for
# 26.04 LTS amd64 on gp3: https://ubuntu.com/aws/docs/aws-how-to/instances/find-ubuntu-images/
AWS_UBUNTU_OWNER = "099720109477"
AWS_UBUNTU_NAME = "ubuntu/images/hvm-ssd-gp3/ubuntu-resolute-26.04-amd64-server-*"
GCP_IMAGE_PROJECT, GCP_IMAGE_FAMILY = "ubuntu-os-cloud", "ubuntu-2604-lts-amd64"
NAME = re.compile(r"[a-z][a-z0-9-]{0,38}[a-z0-9]")
PUBKEY = re.compile(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}")
MIN_PREFIX = 24


class Refused(Exception):
    """Input refused before anything ran (exit 2)."""


VAR = re.compile(r"\{([A-Z_]+)\}")


class Step:
    """One CLI command. `capture` names the variable its stdout sets; `{VAR}`
    inside an argv element is that variable's value (rendered as "${VAR}")."""

    def __init__(self, argv, capture=None):
        self.argv, self.capture = argv, capture

    def render(self):
        words = []
        for a in self.argv:
            parts = VAR.split(a)  # literal, name, literal, name, ..., literal
            words.append("".join(f'"${{{p}}}"' if i % 2 else (shlex.quote(p) if p else "")
                                 for i, p in enumerate(parts)))
        line = " ".join(words)
        return f"{self.capture}=$({line})" if self.capture else line

    def resolve(self, values):
        return [VAR.sub(lambda m: values[m.group(1)], a) for a in self.argv]


def ssh_cidr(text):
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise Refused(f"--ssh-cidr {text!r} is not an IPv4 address or range") from None
    if net.version != 4:
        raise Refused(f"--ssh-cidr {text}: IPv4 only (the SSH rule admits one IPv4 range)")
    if net.prefixlen < MIN_PREFIX:
        raise Refused(f"--ssh-cidr {net}: wider than /{MIN_PREFIX}; the SSH rule admits the person's own "
                      f"address (/32) or a narrow range, never the internet")
    return str(net)


def public_key(path):
    if not path.endswith(".pub"):
        raise Refused(f"--ssh-public-key {path}: not a .pub file; pass the PUBLIC half of the key pair")
    try:
        with open(path, encoding="ascii") as f:
            line = f.readline().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"--ssh-public-key {path}: cannot read it ({e})") from None
    m = PUBKEY.match(line)
    if not m:
        raise Refused(f"--ssh-public-key {path}: not an OpenSSH public key line")
    return m.group(0)


def aws_steps(o):
    base = ["--profile", o.profile, "--region", o.region]
    tags = f"Tags=[{{Key=Name,Value={o.name}}},{{Key={TAG_KEY},Value={TAG_VALUE}}}]"
    group = f"{o.name}-ssh"
    return [
        Step(["aws", "ec2", "describe-images", *base, "--owners", AWS_UBUNTU_OWNER,
              "--filters", f"Name=name,Values={AWS_UBUNTU_NAME}", "Name=state,Values=available",
              "--query", "sort_by(Images, &CreationDate)[-1].ImageId", "--output", "text"], capture="IMAGE_ID"),
        Step(["aws", "ec2", "import-key-pair", *base, "--key-name", o.name,
              "--public-key-material", f"fileb://{o.ssh_public_key}",
              "--tag-specifications", f"ResourceType=key-pair,{tags}",
              "--query", "KeyFingerprint", "--output", "text"]),
        Step(["aws", "ec2", "create-security-group", *base, "--group-name", group,
              "--description", f"agent-fleet {o.name}: SSH from one address range",
              "--tag-specifications", f"ResourceType=security-group,{tags}",
              "--query", "GroupId", "--output", "text"]),
        Step(["aws", "ec2", "authorize-security-group-ingress", *base, "--group-name", group,
              "--protocol", "tcp", "--port", "22", "--cidr", o.ssh_cidr, "--query", "Return", "--output", "text"]),
        Step(["aws", "ec2", "run-instances", *base, "--image-id", "{IMAGE_ID}", "--instance-type", o.size,
              "--key-name", o.name, "--security-groups", group,
              "--block-device-mappings",
              f"DeviceName=/dev/sda1,Ebs={{VolumeSize={o.disk_gb},VolumeType=gp3,DeleteOnTermination=true}}",
              "--metadata-options", "HttpTokens=required",
              "--tag-specifications", f"ResourceType=instance,{tags}", f"ResourceType=volume,{tags}",
              "--query", "Instances[0].InstanceId", "--output", "text"], capture="INSTANCE_ID"),
        Step(["aws", "ec2", "wait", "instance-running", *base, "--instance-ids", "{INSTANCE_ID}"]),
        Step(["aws", "ec2", "describe-instances", *base, "--instance-ids", "{INSTANCE_ID}",
              "--query", "Reservations[0].Instances[0].PublicIpAddress", "--output", "text"], capture="PUBLIC_IP"),
    ]


def gcp_steps(o):
    base = [f"--configuration={o.configuration}", f"--project={o.project}"]
    tag = f"{o.name}-ssh"
    return [
        Step(["gcloud", "compute", "firewall-rules", "create", tag, *base, "--network=default",
              "--direction=INGRESS", "--action=ALLOW", "--rules=tcp:22", f"--source-ranges={o.ssh_cidr}",
              f"--target-tags={tag}", f"--description=agent-fleet {o.name}: SSH from one address range"]),
        Step(["gcloud", "compute", "instances", "create", o.name, *base, f"--zone={o.zone}",
              f"--machine-type={o.size}", f"--image-family={GCP_IMAGE_FAMILY}",
              f"--image-project={GCP_IMAGE_PROJECT}", f"--boot-disk-size={o.disk_gb}GB",
              "--boot-disk-type=pd-balanced", f"--tags={tag}", f"--labels={TAG_KEY}={TAG_VALUE}",
              f"--metadata=ssh-keys={LOGIN_USER}:{o.key_line} {LOGIN_USER}",
              "--no-service-account", "--no-scopes"]),
        Step(["gcloud", "compute", "instances", "describe", o.name, *base, f"--zone={o.zone}",
              "--format=get(networkInterfaces[0].accessConfigs[0].natIP)"], capture="PUBLIC_IP"),
    ]


def ssh_probe(o):
    """The command that proves the VM is reachable: a real SSH login with the key."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
    if o.ssh_public_key.endswith(".pub"):
        argv += ["-i", o.ssh_public_key[:-len(".pub")]]
    return Step(argv + [f"{LOGIN_USER}@{{PUBLIC_IP}}", "true"])


def parse(argv):
    p = argparse.ArgumentParser(prog="provision.py", description="Create one agent-fleet VM.")
    p.add_argument("--provider", required=True, choices=["aws", "gcp"])
    p.add_argument("--region", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--ssh-cidr", required=True)
    p.add_argument("--ssh-public-key", required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--project", help="gcp: the project the VM is created in")
    p.add_argument("--zone", help="gcp: default <region>-b")
    p.add_argument("--size", help="instance type / machine type")
    p.add_argument("--disk-gb", type=int, default=100)
    p.add_argument("--profile", default="agent-fleet", help="aws: the CLI's named profile")
    p.add_argument("--configuration", default="agent-fleet", help="gcp: the gcloud configuration")
    p.add_argument("--wait-ssh", type=int, default=600, help="seconds to wait for SSH; 0 skips the wait")
    o = p.parse_args(argv)
    if not NAME.fullmatch(o.name):
        raise Refused(f"--name {o.name!r}: lowercase letters, digits and hyphens, 2 to 40 characters, "
                      f"starting with a letter")
    if not re.fullmatch(r"[a-z]+(-[a-z]+)+-?[0-9]+", o.region):
        raise Refused(f"--region {o.region!r} is not a region name such as us-east-1 or us-central1")
    if o.provider == "gcp":
        if not o.project:
            raise Refused("--project is required for gcp")
        o.zone = o.zone or f"{o.region}-b"
    if not 10 <= o.disk_gb <= 16384:
        raise Refused(f"--disk-gb {o.disk_gb}: between 10 and 16384")
    o.size = o.size or ("t3.xlarge" if o.provider == "aws" else "e2-standard-4")
    o.ssh_cidr = ssh_cidr(o.ssh_cidr)
    o.key_line = public_key(o.ssh_public_key)
    return o


def run_step(step, values):
    argv = step.resolve(values)
    print(f"+ {step.render()}", flush=True)
    try:
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        return None, f"{argv[0]}: not found on PATH"
    out = r.stdout.strip()
    if r.returncode != 0:
        return None, f"exit {r.returncode}: {r.stderr.strip() or out}"
    if step.capture:
        if not out or out == "None":
            return None, f"printed no value for {step.capture}"
        print(f"  {step.capture}={out}", flush=True)
    return out, None


def main(argv):
    try:
        o = parse(argv)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    steps = aws_steps(o) if o.provider == "aws" else gcp_steps(o)
    probe = ssh_probe(o)
    where = f"profile {o.profile}" if o.provider == "aws" else f"configuration {o.configuration}"
    if o.dry_run:
        print(f"# provision.py --dry-run: {o.provider}, region {o.region}, {where}. Nothing below has run.")
        print("set -eu")
        for s in steps:
            print(s.render())
        print(f"# then, until it succeeds (up to {o.wait_ssh}s):")
        print(probe.render())
        return 0
    values = {}
    for i, s in enumerate(steps, 1):
        out, err = run_step(s, values)
        if err:
            print(f"FAILED at step {i} of {len(steps)} ({' '.join(s.argv[:4])}): {err}", file=sys.stderr)
            print("Nothing after it ran. Read the message, fix the cause, and re-run from the failed step's "
                  "command; the steps before it already exist.", file=sys.stderr)
            return 1
        if s.capture:
            values[s.capture] = out
    if o.wait_ssh > 0:
        deadline = time.monotonic() + o.wait_ssh
        argv = probe.resolve(values)
        print(f"+ {probe.render()}   (repeated until it succeeds, up to {o.wait_ssh}s)", flush=True)
        while True:
            try:
                ok = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            except FileNotFoundError:
                print("FAILED: ssh: not found on PATH", file=sys.stderr)
                return 1
            if ok:
                break
            if time.monotonic() >= deadline:
                print(f"FAILED: ssh to {LOGIN_USER}@{values['PUBLIC_IP']} did not succeed within {o.wait_ssh}s",
                      file=sys.stderr)
                return 1
            time.sleep(5)
    print(f"READY: ssh {LOGIN_USER}@{values['PUBLIC_IP']}   ({o.provider} instance {o.name}, region {o.region})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
