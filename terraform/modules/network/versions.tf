terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Pinned to a major version. AWS provider majors carry breaking changes,
      # and an unpinned provider means two runs of identical code can behave
      # differently after an intervening `terraform init`.
      version = "~> 5.0"
    }
  }
}
