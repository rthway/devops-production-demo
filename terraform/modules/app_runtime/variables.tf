variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. dpd-dev."
  type        = string
}

variable "environment" {
  description = "Environment name. Drives sizing and protection defaults."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "vpc_id" {
  description = "VPC to deploy into."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets for the application tasks and the database."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "At least two private subnets are required: an RDS subnet group spans multiple AZs."
  }
}

variable "public_subnet_ids" {
  description = "Public subnets for the load balancer."
  type        = list(string)
}

# --- application ------------------------------------------------------------

variable "container_image" {
  description = "Fully qualified image reference, including tag."
  type        = string

  validation {
    # A mutable tag makes it impossible to know what is running and makes
    # rollback meaningless, so it is rejected outright rather than warned about.
    condition     = !endswith(var.container_image, ":latest")
    error_message = "Refusing a :latest tag. Deploy an immutable tag such as sha-<gitsha> or vX.Y.Z."
  }
}

variable "container_port" {
  description = "Port the container listens on."
  type        = number
  default     = 8000
}

variable "desired_count" {
  description = "Baseline number of tasks."
  type        = number
  default     = 2
}

variable "task_cpu" {
  description = "Fargate task CPU units (1024 = 1 vCPU)."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "min_capacity" {
  description = "Autoscaling floor."
  type        = number
  default     = 2
}

variable "max_capacity" {
  description = "Autoscaling ceiling. A ceiling is a cost control as much as a capacity one."
  type        = number
  default     = 10
}

# --- database ---------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GiB."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "app"
}

variable "db_username" {
  description = "Database master username. The PASSWORD is never a variable -- see main.tf."
  type        = string
  default     = "app"
}

variable "db_multi_az" {
  description = "Run a standby in a second AZ. Doubles database cost; required for any real availability target."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Automated backup retention in days. Zero disables backups entirely."
  type        = number
  default     = 7

  validation {
    condition     = var.db_backup_retention_days >= 1
    error_message = "Retention must be at least 1 day. Zero disables automated backups and point-in-time recovery."
  }
}

variable "deletion_protection" {
  description = "Block accidental `terraform destroy` of the database."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Never leave this unset -- the default is 'forever', which is a slow-growing bill."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
