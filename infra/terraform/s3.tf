# =============================================================================
# S3 Data Lake Buckets (Medallion Architecture)
# =============================================================================

locals {
  layers = ["bronze", "silver", "gold", "quarantine"]
}

resource "aws_kms_key" "data_lake" {
  description             = "KMS key for LegalDataPlatform data lake"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "data_lake" {
  name          = "alias/${var.project_prefix}-datalake"
  target_key_id = aws_kms_key.data_lake.key_id
}

resource "aws_s3_bucket" "data_lake" {
  for_each      = toset(local.layers)
  bucket        = "${var.project_prefix}-${each.key}-${var.s3_bucket_suffix}"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket_versioning" "data_lake" {
  for_each = aws_s3_bucket.data_lake
  bucket   = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  for_each = aws_s3_bucket.data_lake
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data_lake.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  for_each = aws_s3_bucket.data_lake
  bucket   = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  for_each = aws_s3_bucket.data_lake
  bucket   = each.value.id

  rule {
    id     = "tier-to-glacier-after-90d"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

# -----------------------------------------------------------------------------
# Event notification: Bronze PUT → SQS
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_notification" "bronze_events" {
  bucket = aws_s3_bucket.data_lake["bronze"].id

  queue {
    queue_arn     = aws_sqs_queue.ingest.arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".parquet"
  }

  depends_on = [aws_sqs_queue_policy.ingest]
}
