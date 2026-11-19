terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.80" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Configure remote state before sharing this stack, e.g.:
  # backend "s3" { bucket = "atp-tfstate" key = "v0/terraform.tfstate" region = "us-east-1" }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "atp", Stage = var.stage, ManagedBy = "terraform" }
  }
}
