# Development environment.
#
# A separate ROOT MODULE with its own state, not a workspace. Workspaces share
# one backend key and one set of provider credentials, so a mistyped
# `terraform destroy` in dev can reach prod state. Separate roots make that
# physically impossible.

locals {
  name_prefix = "dpd-dev"

  tags = {
    Environment = "dev"
    CostCenter  = "engineering"
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix             = local.name_prefix
  vpc_cidr                = "10.10.0.0/16"
  availability_zone_count = 2

  # One NAT gateway. A NAT gateway costs roughly the same per month as the
  # rest of this environment combined, and dev does not need AZ-redundant
  # egress.
  single_nat_gateway = true

  tags = local.tags
}

module "app_runtime" {
  source = "../../modules/app_runtime"

  name_prefix = local.name_prefix
  environment = "dev"

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids

  container_image = var.container_image

  # Small and cheap: dev exists to catch configuration errors, not to serve load.
  desired_count = 1
  task_cpu      = 256
  task_memory   = 512
  min_capacity  = 1
  max_capacity  = 3

  db_instance_class        = "db.t4g.micro"
  db_allocated_storage     = 20
  db_multi_az              = false
  db_backup_retention_days = 1

  # Off in dev so the environment can actually be torn down.
  deletion_protection = false
  log_retention_days  = 7

  tags = local.tags
}
