# =============================================================================
# LegalDataPlatform — AWS Infrastructure
# =============================================================================
# Provisioned resources:
#   - S3 buckets (Bronze, Silver, Gold, Quarantine) with versioning + encryption
#   - KMS keys for at-rest encryption
#   - SQS queue with DLQ for pipeline triggering
#   - IAM roles and policies
#   - Lambda functions: s3_event_ingest and sqs_pipeline_trigger
#   - RDS PostgreSQL (optional, commented out by default — use Aurora Serverless)
#   - Glue Data Catalog databases
#   - CloudWatch log groups and alarms
# =============================================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  backend "s3" {
    bucket         = "ldp-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "ldp-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "LegalDataPlatform"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = "data-engineering"
    }
  }
}
