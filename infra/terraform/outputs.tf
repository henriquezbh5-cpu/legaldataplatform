output "bronze_bucket" {
  description = "Bronze S3 bucket name."
  value       = aws_s3_bucket.data_lake["bronze"].id
}

output "silver_bucket" {
  description = "Silver S3 bucket name."
  value       = aws_s3_bucket.data_lake["silver"].id
}

output "gold_bucket" {
  description = "Gold S3 bucket name."
  value       = aws_s3_bucket.data_lake["gold"].id
}

output "quarantine_bucket" {
  description = "Quarantine S3 bucket name."
  value       = aws_s3_bucket.data_lake["quarantine"].id
}

output "ingest_queue_url" {
  description = "SQS queue URL for ingest events."
  value       = aws_sqs_queue.ingest.url
}

output "aurora_endpoint" {
  description = "Aurora writer endpoint (null if no VPC configured)."
  value       = try(aws_rds_cluster.aurora[0].endpoint, null)
}

output "db_secret_arn" {
  description = "Secrets Manager ARN for DB master credentials."
  value       = aws_secretsmanager_secret.db_master.arn
  sensitive   = true
}
