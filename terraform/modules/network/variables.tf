variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. dpd-dev."
  type        = string

  validation {
    # Names feed into DNS labels and security group names downstream, so an
    # invalid prefix would otherwise fail far away from its cause.
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name_prefix))
    error_message = "name_prefix must be 2-21 chars, lowercase alphanumeric or hyphen, starting with a letter."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "availability_zone_count" {
  description = "Number of availability zones to spread subnets across."
  type        = number
  default     = 2

  validation {
    # Two is the minimum for an RDS subnet group and for any meaningful
    # availability story; beyond three the NAT cost rarely earns its keep.
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 3
    error_message = "availability_zone_count must be between 2 and 3."
  }
}

variable "single_nat_gateway" {
  description = "Route all private egress through one NAT gateway. Cheaper, but a single point of failure -- acceptable in dev, not in prod."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
