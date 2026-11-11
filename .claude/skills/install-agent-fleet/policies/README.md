# Least-privilege policies for one agent-fleet VM

Two files, one per provider. Each grants what `../provision.py` and the
day-to-day commands in `../targets/aws.md` and `../targets/gcp.md` use - create
one VM with its boot disk, its SSH key and its SSH firewall rule, then
describe, start, stop and delete it - and nothing else: no IAM, no other
service, no wildcard action.

| File | Provider | Holds |
|---|---|---|
| `aws-one-vm.json` | AWS | an IAM identity-based policy, attached to a dedicated IAM user |
| `gcp-one-vm-role.json` | Google Cloud | a custom role definition, granted to a dedicated service account on one project |

**The tables below are the contract `../provision.test.py` enforces**: every
action or permission in a policy file has exactly one row here, every row names
one in the file, and no action carries a wildcard. Changing a policy means
changing its table in the same commit, with the page that defines the new name
and the date it was checked there.

## How the scope is held

- **AWS: tags.** Every resource the policy lets the identity create must carry
  the tag `agent-fleet=managed` at creation (`aws:RequestTag`), tags can only be
  written while creating (`ec2:CreateAction`), and every start, stop, terminate,
  rule change and delete needs that tag on the resource (`aws:ResourceTag`). The
  identity cannot touch an instance, security group or key pair it did not
  create, even in a shared account. The `Describe*` actions take `Resource: "*"`
  because EC2 defines no resource type for them; they read, never write.
- **Google Cloud: the project.** IAM conditions cannot read a Compute Engine
  label, so the role is granted on a project that holds nothing but the fleet
  VM, and the project is the boundary. The VM is created with no service
  account, so the role needs no `iam.serviceAccounts.actAs`.
- **Neither provider can refuse a world-open SSH rule in IAM**: no AWS condition
  key and no Google Cloud permission reads an ingress rule's source range.
  `../provision.py` refuses any range wider than /24 before it runs anything.

## AWS: `aws-one-vm.json`

Every action was checked by exact name against the action table of the EC2
service authorization reference, and every action, resource type and condition
key against AWS's machine-readable service reference
(`https://servicereference.us-east-1.amazonaws.com/v1/ec2/ec2.json`), which
also confirmed that each condition key applies to the resource types its
statement names.

| Action | Needed for | Defined in | Checked |
|---|---|---|---|
| `ec2:DescribeImages` | finding the newest Ubuntu 26.04 image | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DescribeImages | 2026-11-06 |
| `ec2:DescribeInstances` | the instance's state and public address; `aws ec2 wait instance-running` | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DescribeInstances | 2026-11-06 |
| `ec2:DescribeKeyPairs` | listing the fleet's key pair; the credential check | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DescribeKeyPairs | 2026-11-06 |
| `ec2:DescribeSecurityGroups` | reading the SSH rule's current address range | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DescribeSecurityGroups | 2026-11-06 |
| `ec2:RunInstances` | launching the instance with its boot volume | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-RunInstances | 2026-11-06 |
| `ec2:CreateTags` | tagging the instance, volume, group and key pair as they are created | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-CreateTags | 2026-11-06 |
| `ec2:CreateSecurityGroup` | the SSH security group | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-CreateSecurityGroup | 2026-11-06 |
| `ec2:AuthorizeSecurityGroupIngress` | the SSH rule for the person's address range | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-AuthorizeSecurityGroupIngress | 2026-11-06 |
| `ec2:RevokeSecurityGroupIngress` | replacing the SSH rule when the address changes | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-RevokeSecurityGroupIngress | 2026-11-06 |
| `ec2:DeleteSecurityGroup` | removing the group with the VM | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DeleteSecurityGroup | 2026-11-06 |
| `ec2:ImportKeyPair` | the SSH public key | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-ImportKeyPair | 2026-11-06 |
| `ec2:DeleteKeyPair` | removing the key with the VM | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-DeleteKeyPair | 2026-11-06 |
| `ec2:StartInstances` | starting the VM | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-StartInstances | 2026-11-06 |
| `ec2:StopInstances` | stopping the VM | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-StopInstances | 2026-11-06 |
| `ec2:TerminateInstances` | deleting the VM; its boot volume goes with it | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-action-TerminateInstances | 2026-11-06 |

| Condition key | Needed for | Defined in | Checked |
|---|---|---|---|
| `aws:RequestTag/agent-fleet` | create only what carries the fleet tag | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-aws_RequestTag___TagKey_ | 2026-11-06 |
| `aws:ResourceTag/agent-fleet` | change only what carries the fleet tag | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-aws_ResourceTag___TagKey_ | 2026-11-06 |
| `ec2:CreateAction` | write tags only while creating | https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html#list_ec2-ec2_CreateAction | 2026-11-06 |

## Google Cloud: `gcp-one-vm-role.json`

Every permission was checked by exact name against the Compute Engine roles and
permissions page (`https://docs.cloud.google.com/iam/docs/roles-permissions/compute`)
and through the IAM API's `permissions:queryTestablePermissions` on a project:
every one is GA and SUPPORTED in custom roles. The page in each row is the method
or how-to page that requires it.

| Permission | Needed for | Defined in | Checked |
|---|---|---|---|
| `compute.instances.create` | creating the VM | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert | 2026-11-06 |
| `compute.disks.create` | its boot disk | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.instances.setMetadata` | the SSH key in instance metadata | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.instances.setLabels` | the `agent-fleet=managed` label | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.instances.setTags` | the network tag the SSH rule targets | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.subnetworks.use` | attaching the VM to the default network's subnet | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.subnetworks.useExternalIp` | its external address, which SSH reaches | https://docs.cloud.google.com/compute/docs/instances/create-start-instance | 2026-11-06 |
| `compute.zoneOperations.get` | waiting for a VM operation to finish | https://docs.cloud.google.com/compute/docs/reference/rest/v1/zoneOperations/get | 2026-11-06 |
| `compute.instances.get` | the VM's state and external address | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/get | 2026-11-06 |
| `compute.instances.list` | listing the VM; the credential check | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/list | 2026-11-06 |
| `compute.instances.start` | starting the VM | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/start | 2026-11-06 |
| `compute.instances.stop` | stopping the VM | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/stop | 2026-11-06 |
| `compute.instances.delete` | deleting the VM; its boot disk goes with it | https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/delete | 2026-11-06 |
| `compute.firewalls.create` | the SSH firewall rule | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/insert | 2026-11-06 |
| `compute.networks.updatePolicy` | adding, changing or deleting a rule on the network | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/insert | 2026-11-06 |
| `compute.globalOperations.get` | waiting for a firewall operation to finish | https://docs.cloud.google.com/compute/docs/reference/rest/v1/globalOperations/get | 2026-11-06 |
| `compute.firewalls.get` | reading the rule | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/get | 2026-11-06 |
| `compute.firewalls.list` | listing the rules | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/list | 2026-11-06 |
| `compute.firewalls.update` | moving the rule to a new address range | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/patch | 2026-11-06 |
| `compute.firewalls.delete` | removing the rule with the VM | https://docs.cloud.google.com/compute/docs/reference/rest/v1/firewalls/delete | 2026-11-06 |

## Re-checking

A provider renames or retires a permission without notice to its users. Before
relying on a file whose `Checked` dates are old, look each name up again at the
page in its row and update the date; a name that is gone there is gone from the
policy too.
