terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # No access keys here, ever. Credentials come from the environment: an SSO
  # profile locally, and OIDC federation in GitHub Actions. A static key in a
  # provider block is a key in git history forever.

  default_tags {
    # Applied to every taggable resource automatically, so cost allocation
    # does not depend on remembering to tag each resource by hand.
    tags = {
      Project     = "devops-production-demo"
      Environment = "prod"
      ManagedBy   = "terraform"
      Repository  = "github.com/rthway/devops-production-demo"
    }
  }
}
