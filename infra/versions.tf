terraform {
  required_version = ">= 1.10"

  # Remote state (bucket from infra/bootstrap), with S3-native locking. Credentials:
  # locally `terraform init -backend-config="profile=electro"`; in GitHub Actions the
  # OIDC role.
  backend "s3" {
    bucket       = "sadi-demand-tfstate-882856016817"
    key          = "infra/terraform.tfstate"
    region       = "sa-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      project    = "sadi-demand-forecast"
      managed_by = "terraform"
    }
  }
}
