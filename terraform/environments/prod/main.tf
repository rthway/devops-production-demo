# Production environment.
#
# Same modules as dev, different inputs. That is the entire point of the
# module split: prod is not a fork of dev that has drifted, it is the same
# code with different sizing and different protection settings.

locals {
  name_prefix = "dpd-prod"

  tags = {
    Environment = "prod"
    CostCenter  = "engineering"
    Compliance  = "required"
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix = local.name_prefix
  # A distinct, non-overlapping CIDR from dev. Overlapping ranges make VPC
  # peering or a future transit gateway impossible without renumbering.
  vpc_cidr                = "10.20.0.0/16"
  availability_zone_count = 3

  # One NAT per AZ. Losing an AZ must not remove internet egress for the
  # tasks still running in the other two.
  single_nat_gateway = false

  tags = local.tags
}

module "app_runtime" {
  source = "../../modules/app_runtime"

  name_prefix = local.name_prefix
  environment = "prod"

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids

  container_image = var.container_image

  desired_count = 3
  task_cpu      = 1024
  task_memory   = 2048
  min_capacity  = 3
  max_capacity  = 20

  db_instance_class    = "db.t4g.medium"
  db_allocated_storage = 100

  # Standby in a second AZ, 30 days of backups, and the database cannot be
  # destroyed by an apply.
  db_multi_az              = true
  db_backup_retention_days = 30
  deletion_protection      = true

  log_retention_days = 90

  tags = local.tags
}
