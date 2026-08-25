terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Production state backend — create the bucket first, then uncomment:
  # backend "s3" {
  #   bucket         = "ara-terraform-state-<account-id>"
  #   key            = "appointment-agent/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "ara-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
