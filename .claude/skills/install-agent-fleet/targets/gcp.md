# Target: an instance in Google Cloud

Claude guides the person through a dedicated Google Cloud service account that
can create and manage one VM and nothing else, puts its credential where the
`gcloud` CLI keeps it on the person's LOCAL machine, and creates the VM with
`../provision.py`. The guide ends when the VM answers SSH with the person's
key; the common steps of this skill's `SKILL.md` take over from there. Every
command here runs on the local machine (Linux, or macOS as `macos.md`
describes).

Placeholders: `<project>` (the project id), `<region>` (such as `us-central1`),
`<zone>` (`<region>-b` unless the person picks another), `<name>` (the VM's
name: lowercase letters, digits and hyphens, such as `fleet-1`), `<address>`
(the VM's external IPv4 address, which `provision.py` prints) and `<fleet>` (the
fleet checkout this file was read from).

---

## 1. What the person needs

- A Google Cloud billing account, and a project that holds nothing but the
  fleet VM. **The project is the boundary**: IAM conditions cannot read a
  Compute Engine label, so the role below is granted on this one project, and a
  project shared with other work would put that work in the role's reach.
- The Google Cloud CLI on the local machine (https://cloud.google.com/sdk/docs/install);
  `gcloud --version` answers.
- An SSH key pair on the local machine: `ls ~/.ssh/id_ed25519.pub`, else
  `ssh-keygen -t ed25519`.

## 2. The dedicated identity (the person, as the project's owner)

The role is `../policies/gcp-one-vm-role.json`: create, read, start, stop and
delete instances and their boot disks, set their SSH key, label and network
tag, and manage firewall rules on the project's network. `../policies/README.md`
names the Google page behind every permission. The VM is created with no
service account of its own, so the role needs no permission to act as one.

In the person's own terminal or Cloud Shell, signed in as the project's owner
(`gcloud auth login`):

```bash
gcloud projects create <project>
gcloud billing projects link <project> --billing-account=<billing account id>
gcloud services enable compute.googleapis.com --project=<project>
gcloud iam roles create agentFleetOneVm --project=<project> \
  --file=<fleet>/.claude/skills/install-agent-fleet/policies/gcp-one-vm-role.json
gcloud iam service-accounts create agent-fleet-provisioner --project=<project> --display-name="agent-fleet provisioner"
SA=$(gcloud iam service-accounts list --project=<project> --filter='email ~ ^agent-fleet-provisioner@' --format='value(email)')
gcloud projects add-iam-policy-binding <project> --member="serviceAccount:$SA" \
  --role="projects/<project>/roles/agentFleetOneVm" --condition=None
install -d -m 700 ~/.agent-fleet-secrets
gcloud iam service-accounts keys create ~/.agent-fleet-secrets/agent-fleet-provisioner.json --iam-account="$SA"
```

`gcloud billing accounts list` shows the billing account id. The same in the
console: a new project; **APIs and services**, enable the Compute Engine API;
**IAM and admin, Roles, Create role**, ID `agentFleetOneVm`, adding each name in
the file's `includedPermissions`; **Service accounts, Create service account**
`agent-fleet-provisioner`, granted that role; then its **Keys** tab, **Add key,
JSON**, which downloads the key file.

**Never through Claude's session**: the last step writes a credential. An
organization created on or after 2024-05-03 refuses that step by default
(`constraints/iam.managed.disableServiceAccountKeyCreation`). There, the
person grants their own account `roles/iam.serviceAccountTokenCreator` on the
service account instead, and section 3 uses impersonation.

## 3. The credential on the local machine

A configuration of its own, so the person's everyday `gcloud` login stays as it
is. These commands name the key file's PATH, never its content, so Claude runs
them. The key reaches that path, `~/.agent-fleet-secrets/agent-fleet-provisioner.json`,
by section 2's command, by the paste way of `../SKILL.md`, or through
`/safe-box` served on this machine with
`FLEET_SECRETS_DIR=~/.agent-fleet-secrets` and the name
`agent-fleet-provisioner.json` (a relative path lands in that directory): its
form drops line breaks, which a JSON key survives.

```bash
gcloud config configurations create agent-fleet --no-activate
gcloud auth activate-service-account --key-file=$HOME/.agent-fleet-secrets/agent-fleet-provisioner.json --configuration=agent-fleet
gcloud config set project <project> --configuration=agent-fleet
rm -f ~/.agent-fleet-secrets/agent-fleet-provisioner.json
```

`activate-service-account` imports the key into gcloud's own credential store
under `~/.config/gcloud/`, where the CLI keeps every configuration and
credential (https://docs.cloud.google.com/sdk/docs/configurations), so the
downloaded file is deleted. With impersonation instead (section 2), the second
line is `gcloud auth login --configuration=agent-fleet` with the person's own
account, followed by
`gcloud config set auth/impersonate_service_account <service account email> --configuration=agent-fleet`;
every command in the configuration then acts as the service account, and the
person's own credential sits in the same store.

**Claude never opens, prints or copies anything under `~/.config/gcloud/`, and
never copies a credential to the VM.** It names the configuration on every
command (`--configuration=agent-fleet`), which is all gcloud needs. The VM runs
with no service account and holds no Google Cloud credential at all.

Claude checks the configuration with a call the role allows that prints only
instance names (none yet):

```bash
gcloud compute instances list --configuration=agent-fleet --format='value(name)'
```

An empty line and exit 0 mean it works; `PERMISSION_DENIED` names the missing
permission or a role that is not bound.

## 4. Region, size and cost

- **Region**: the one closest to the person; with no preference,
  `us-central1`, where the estimate below was measured. The zone is
  `<region>-b` unless `--zone` names another.
- **Size**: `e2-standard-4`, 4 vCPU and 16 GB, the size `linux.md` section 4
  derives for 4 agents.
- **Image**: Ubuntu 26.04 LTS for amd64, the image family `ubuntu-2604-lts-amd64`
  in `ubuntu-os-cloud` (`linux.md` section 1).
- **Disk**: 100 GB balanced persistent disk, deleted with the VM.

**Monthly cost estimate, `us-central1`, on demand, 730 hours:**

| Item | Unit price | Per month |
|---|---|---|
| `e2-standard-4`: 4 vCPU, 16 GiB | $0.02181159 per vCPU-hour, $0.00292353 per GiB-hour | $97.84 |
| 100 GiB balanced persistent disk | $0.10 per GiB-month | $10.00 |
| one external IPv4 address on a standard VM | $0.005 per hour; the catalog prices the first 720 hours a month at $0 | $0.05 to $3.65 |
| **Total** | | **$107.89 to $111.49** |

The address line depends on whether the billing account's other external
addresses have used those 720 hours.

Source: the Cloud Billing Catalog API,
`https://cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus` (Compute
Engine), SKUs `CF4E-A0C7-E3BF` (E2 instance core, Americas), `F449-33EC-A5EF`
(E2 instance RAM, Americas), `6AE1-525F-8B80` (balanced PD capacity) and
`C054-7F72-A02E` (external IP on a standard VM), effective
2026-11-06T08:00:00Z, read 2026-11-06. **A dated measurement, not a quote**: it
leaves out tax, network egress and any discount or free-tier credit. Before
quoting it, read those SKUs again or use the Google Cloud pricing calculator.

## 5. Create the VM (Claude, on the local machine)

1. The person's public address: `curl -fsS https://checkip.amazonaws.com`. The
   SSH rule admits that one address (`/32`).
2. The dry run, shown to the person as it is:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/provision.py" --provider gcp --project <project> --region <region> --name <name> \
     --ssh-cidr <the address from step 1>/32 --ssh-public-key ~/.ssh/id_ed25519.pub --dry-run
   ```

3. On the person's OK, the same line with `--apply`. It prints each command as
   it runs it and ends with `READY: ssh ubuntu@<address>`. A failed step stops
   the run and names itself; the steps before it already exist, so the fix is
   to run the remaining commands from the dry run, or to remove what exists
   (section 7) and apply again.

**The target is ready: `<admin-host>` is `ubuntu@<address>`.** Google's guest
agent creates `ubuntu` from the key in the instance metadata and gives it sudo
with no password, so the bootstrap's stdin stays empty, and `ubuntu` is the
administrator: the agents run as the separate agents user the bootstrap
creates, without sudo (`../SKILL.md`, "Two users on the target"). **That user's
key never goes into the instance metadata.** The guest agent adds every user it
provisions from metadata keys to its `google-sudoers` group, which is sudo with
no password, and leaves alone the accounts it did not create
(https://github.com/GoogleCloudPlatform/guest-agent, checked 2026-11-06); the
bootstrap writes the key into the agents user's own `authorized_keys` instead.

## 6. Day to day

Every command takes `--configuration=agent-fleet`.

```bash
gcloud compute instances list --filter=labels.agent-fleet=managed \
  --format='table(name,zone.basename(),status,networkInterfaces[0].accessConfigs[0].natIP)'
gcloud compute instances stop <name> --zone=<zone>
gcloud compute instances start <name> --zone=<zone>
```

A stopped VM costs nothing per hour; its disk still does. **Its external
address changes at every start**: read it again with the first command. When
the person's own address changes:

```bash
gcloud compute firewall-rules update <name>-ssh --source-ranges=<new address>/32
```

## 7. Removing it

```bash
gcloud compute instances delete <name> --zone=<zone> --quiet
gcloud compute firewall-rules delete <name>-ssh --quiet
```

Deleting the VM deletes its boot disk and everything on it. Then the person
deletes the project, or the service account and the role, and the local
configuration: `gcloud config configurations delete agent-fleet`.
