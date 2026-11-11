# Target: an instance in AWS

Claude guides the person through a dedicated AWS identity that can create and
manage one VM and nothing else, puts its credential where the AWS CLI keeps
it on the person's LOCAL machine, and creates the VM with `../provision.py`.
The guide ends when the VM answers SSH with the person's key; the common steps
of this skill's `SKILL.md` take over from there. Every command here runs on
the local machine (Linux, or macOS as `macos.md` describes).

Placeholders: `<region>` (an AWS region, such as `us-east-1`), `<name>` (the
VM's name: lowercase letters, digits and hyphens, such as `fleet-1`),
`<address>` (the VM's public IPv4 address, which `provision.py` prints) and
`<fleet>` (the fleet checkout this file was read from).

---

## 1. What the person needs

- An AWS account, and a console sign-in that can create IAM users and policies.
- The AWS CLI version 2 on the local machine
  (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html);
  `aws --version` prints `aws-cli/2.`.
- An SSH key pair on the local machine: `ls ~/.ssh/id_ed25519.pub`, else
  `ssh-keygen -t ed25519`.
- The region's default VPC, which every account has unless someone deleted it
  (VPC console, **Your VPCs**: one row says **Default VPC: Yes**). The VM is
  launched into it.

## 2. The dedicated identity (the person, in the AWS console)

The policy is `../policies/aws-one-vm.json`. It lets the identity create an
instance, its boot volume, one security group and one key pair only when they
carry the tag `agent-fleet=managed`, and start, stop, change or delete only
what carries that tag; `../policies/README.md` says how, and names the AWS page
behind every action.

1. **IAM, Policies, Create policy**, the **JSON** tab: replace the editor's
   content with the file's, **Next**, name it `agent-fleet-one-vm`, **Create
   policy**.
2. **IAM, Users, Create user**: name `agent-fleet-provisioner`, leave console
   access off, **Next**; **Attach policies directly**, tick
   `agent-fleet-one-vm`, **Next**, **Create user**.
3. Open the user, the **Security credentials** tab, **Create access key**: use
   case **Command Line Interface (CLI)**, confirm, **Create access key**. Keep
   the page open for section 3.

The same from the person's own terminal, signed in with their administrator
profile. **Never through Claude's session**: the last command prints the
secret key.

```bash
aws iam create-policy --policy-name agent-fleet-one-vm \
  --policy-document file://<fleet>/.claude/skills/install-agent-fleet/policies/aws-one-vm.json \
  --query Policy.Arn --output text
aws iam create-user --user-name agent-fleet-provisioner
aws iam attach-user-policy --user-name agent-fleet-provisioner --policy-arn <the ARN the first command printed>
aws iam create-access-key --user-name agent-fleet-provisioner
```

## 3. The credential on the local machine

The CLI keeps the key in `~/.aws/credentials` and the region in
`~/.aws/config`, each under the profile `agent-fleet`
(https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html).
Either the person runs `aws configure --profile agent-fleet` in their own
terminal and answers its prompts (the region `<region>`, the output `json`),
or the two values come in by the paste way of `../SKILL.md` or through
`/safe-box` served on this machine with `FLEET_SECRETS_DIR=~/.agent-fleet-secrets`
and the names `aws-access-key-id` and `aws-secret-access-key`. Then Claude
writes the profile from those two files, which neither a command line nor any
output ever carries, when `~/.aws/credentials` has no `[agent-fleet]` section
yet (the file is absent, or `grep -q '^\[agent-fleet\]' ~/.aws/credentials`
exits 1; otherwise the person removes the old section first):

```bash
install -d -m 700 ~/.aws
( umask 077 && { printf '\n[agent-fleet]\naws_access_key_id = '; cat ~/.agent-fleet-secrets/aws-access-key-id
  printf '\naws_secret_access_key = '; cat ~/.agent-fleet-secrets/aws-secret-access-key; printf '\n'; } >> ~/.aws/credentials )
chmod 600 ~/.aws/credentials
aws configure set region <region> --profile agent-fleet
aws configure set output json --profile agent-fleet
rm -f ~/.agent-fleet-secrets/aws-access-key-id ~/.agent-fleet-secrets/aws-secret-access-key
```

`cat` reads each value from its file into the credentials file, so it is never
an argument, and nothing prints it. The person then closes the page that
showed the key.

**Claude never opens, prints or copies either file, and never copies a
credential to the VM.** It names the profile on every command, which is all the
CLI needs. The VM holds no AWS credential at all: nothing on it manages AWS.

Claude checks the profile with a call the policy allows and that prints a
count, not an identity:

```bash
aws ec2 describe-key-pairs --profile agent-fleet --region <region> --query 'length(KeyPairs)'
```

A number means the credential works. `AuthFailure` means the key is wrong;
`UnauthorizedOperation` means the policy is not attached to the user.

## 4. Region, size and cost

- **Region**: the one closest to the person; with no preference, `us-east-1`,
  where the estimate below was measured.
- **Size**: `t3.xlarge`, 4 vCPU and 16 GiB, the size `linux.md` section 4
  derives for 4 agents. A t3 sustains 40% of each vCPU (1.6 vCPUs) and bursts
  above that; the measured agents average about 0.34 cores each. A project
  that builds for hours every day takes `--size m7i.xlarge`, the same size
  without the burst limit.
- **Image**: Ubuntu 26.04 LTS for amd64, Canonical's (`linux.md` section 1).
- **Disk**: 100 GiB gp3, deleted with the instance.

**Monthly cost estimate, `us-east-1`, on demand, 730 hours:**

| Item | Unit price | Per month |
|---|---|---|
| `t3.xlarge`, Linux | $0.1664 per hour | $121.47 |
| 100 GiB gp3 | $0.08 per GB-month | $8.00 |
| one public IPv4 address in use | $0.005 per hour | $3.65 |
| **Total** | | **$133.12** |

With `m7i.xlarge` ($0.2016 per hour, $147.17 a month) the total is $158.82.

Source: the AWS Price List bulk API's offer files,
https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv
and
https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/us-east-1/index.csv,
publication 2026-11-05, prices effective 2026-11-01, read 2026-11-06. **A dated
measurement, not a quote**: it leaves out tax, data transfer, a t3's surplus
CPU credits ($0.05 per vCPU-hour above the 24-hour baseline, same file) and any
free-tier or savings-plan discount. Before quoting it, re-read those two files
or the AWS pricing calculator.

## 5. Create the VM (Claude, on the local machine)

1. The person's public address: `curl -fsS https://checkip.amazonaws.com`. The
   SSH rule admits that one address (`/32`).
2. The dry run, shown to the person as it is:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/provision.py" --provider aws --region <region> --name <name> \
     --ssh-cidr <the address from step 1>/32 --ssh-public-key ~/.ssh/id_ed25519.pub --dry-run
   ```

3. On the person's OK, the same line with `--apply`. It prints each command as
   it runs it and ends with `READY: ssh ubuntu@<address>`. A failed step stops
   the run and names itself; the steps before it already exist, so the fix is
   to run the remaining commands from the dry run, or to remove what exists
   (section 7) and apply again.

**The target is ready: `<admin-host>` is `ubuntu@<address>`.** Ubuntu's cloud
image gives `ubuntu` sudo with no password, so the bootstrap's stdin stays
empty, and `ubuntu` is the administrator: the agents run as the separate agents
user the bootstrap creates, without sudo (`../SKILL.md`, "Two users on the
target").

## 6. Day to day

Every command takes `--profile agent-fleet --region <region>`.

```bash
aws ec2 describe-instances --filters Name=tag:Name,Values=<name> Name=tag:agent-fleet,Values=managed \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,PublicIpAddress]' --output text
aws ec2 stop-instances --instance-ids <instance-id>
aws ec2 start-instances --instance-ids <instance-id>
```

A stopped instance costs nothing per hour; its disk still does. **Its public
address changes at every start**: read it again with the first command.

When the person's own address changes, read the old range and swap it:

```bash
aws ec2 describe-security-groups --group-names <name>-ssh --query 'SecurityGroups[0].IpPermissions[].IpRanges[].CidrIp'
aws ec2 revoke-security-group-ingress --group-name <name>-ssh --protocol tcp --port 22 --cidr <old range>
aws ec2 authorize-security-group-ingress --group-name <name>-ssh --protocol tcp --port 22 --cidr <new address>/32
```

## 7. Removing it

```bash
aws ec2 terminate-instances --instance-ids <instance-id>
aws ec2 wait instance-terminated --instance-ids <instance-id>
aws ec2 delete-security-group --group-name <name>-ssh
aws ec2 delete-key-pair --key-name <name>
```

Terminating deletes the boot disk and everything on it. Then the person deletes
the user `agent-fleet-provisioner` and the policy `agent-fleet-one-vm` in the
IAM console, and the `agent-fleet` sections from `~/.aws/credentials` and
`~/.aws/config` by hand.
