variable "aws_region" {
  description = "AWS region for this environment."
  type        = string
  default     = "ap-south-1"
}

variable "container_image" {
  description = "Immutable image reference to deploy. CI passes -var container_image=...:sha-<gitsha>."
  type        = string
  default     = "ghcr.io/rthway/devops-production-demo:1.0.0"
}
