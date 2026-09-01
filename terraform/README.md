# Terraform

Infrastructure for `devops-production-demo`: an ALB in front of ECS Fargate
tasks, backed by RDS PostgreSQL, inside a purpose-built VPC.

## Layout

```text
terraform/
├── modules/
│   ├── network/       VPC, public/private subnets, NAT, flow logs
│   └── app_runtime/   ALB, ECS Fargate, RDS, Secrets Manager, IAM, autoscaling
└── environments/
    ├── dev/           own state, small sizing, destroyable
    └── prod/          own state, HA sizing, deletion protection
```

## Environments are separate root modules, not workspaces

The most important structural decision here. Workspaces share one backend key
and one set of provider credentials, so a mistyped `terraform destroy` in dev
can reach prod state. Separate root modules with separate state keys — ideally
separate buckets, better still separate AWS accounts — make that physically
impossible.

The cost is a little duplication between the two `main.tf` files. That is the
correct trade.

## Usage

```bash
cd terraform/environments/dev

terraform init
terraform fmt -check -recursive
terraform validate

terraform plan  -var container_image=ghcr.io/rthway/devops-production-demo:sha-abc123
terraform apply -var container_image=ghcr.io/rthway/devops-production-demo:sha-abc123
```

`terraform validate` needs no credentials, which is why CI can run it on a pull
request from a fork. `plan` and `apply` do.

## Remote state

Local state is unacceptable for anything shared: it lives on one laptop, has no
locking, and holds every secret the configuration touches in plain text.

Copy `backend.tf.example` to `backend.tf`, fill in the bucket and KMS key, then
run `terraform init -migrate-state`. It ships as `.example` because bucket and
key names are account-specific, and a backend block pointing at someone else's
bucket is worse than no backend block at all.

Requirements for the state bucket: versioning on, encryption with a
customer-managed key, public access blocked, locking enabled.

## Credentials

There are none in this tree, and none should ever be added.

- **Locally:** an AWS SSO profile, or the standard environment variables.
- **In CI:** OIDC federation. A short-lived token is minted per run, so there
  is no long-lived key to leak.
- **The database password is generated** by `random_password` and stored in
  Secrets Manager. It is not an input variable, so it cannot arrive through a
  `.tfvars` file, a CI log, or someone's shell history.

Honest caveat: the generated password is still recorded in Terraform state.
That is why the backend must be encrypted and access controlled. Eliminating it
entirely means `manage_master_user_password` and letting RDS own rotation.

`*.tfvars` is gitignored; only `*.tfvars.example` is committed.

## Notable decisions

| Decision | Reasoning |
|---|---|
| ECS Fargate, not EKS | One service does not justify a control plane |
| `container_image` rejects `:latest` | A mutable tag makes rollback meaningless |
| Two IAM roles (execution + task) | The task role has no policy at all; the app calls no AWS API |
| Security groups reference each other by ID | Stays correct when subnets are renumbered |
| No egress rule on the database SG | It has no reason to originate a connection |
| `rds.force_ssl = 1` | Without it TLS is available but not required |
| `deployment_circuit_breaker` with rollback | A broken image self-heals instead of crash-looping |
| `ignore_changes = [desired_count]` | The autoscaler owns it; Terraform must not fight it |
| One NAT in dev, one per AZ in prod | A NAT gateway costs roughly as much as the rest of dev |
| Distinct VPC CIDRs per environment | Overlapping ranges block future peering |
| Validation on `db_backup_retention_days >= 1` | Zero silently disables PITR |

## Verification status

```text
terraform fmt -check -recursive      PASS   (verified)
terraform init  (dev and prod)       PASS   (verified, -backend=false)
terraform validate (dev and prod)    PASS   (verified)

terraform plan / apply               NOT EXECUTED
  Reason:   no AWS credentials available on the development machine.
  How:      configure AWS SSO or CI OIDC, then run `terraform plan` as above.
  Expected: a plan creating the VPC, subnets, NAT, ALB, ECS cluster and
            service, RDS instance, Secrets Manager secret and IAM roles.
```

Nothing in this directory has been applied to a cloud account.
