variable "aws_region" {
  type        = string
  description = "AWS region for all resources."
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment name (dev, staging, prod)."
  default     = "prod"
}

variable "project_prefix" {
  type        = string
  description = "Prefix used for resource naming."
  default     = "ldp"
}

variable "s3_bucket_suffix" {
  type        = string
  description = "Suffix appended to S3 bucket names for global uniqueness."
}

variable "lambda_runtime" {
  type    = string
  default = "python3.11"
}

variable "prefect_api_url" {
  type        = string
  description = "Prefect API endpoint that SQS trigger Lambda will call."
  sensitive   = true
}

variable "prefect_deployment_id" {
  type        = string
  description = "Prefect deployment ID for the ingestion flow."
}

variable "prefect_api_key" {
  type        = string
  description = "Prefect Cloud API key (optional, if using Prefect Cloud)."
  sensitive   = true
  default     = ""
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where private resources (RDS, Lambda VPC config) live."
  default     = ""
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for Lambda and RDS."
  default     = []
}
